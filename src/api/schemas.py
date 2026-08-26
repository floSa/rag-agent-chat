from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

# Identifiant d'élément : hash sha256 tronqué à 10 caractères produit par
# l'ingestion. Validé strictement car interpolé dans les requêtes nGQL.
ElementId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{10}$")]


# ─── Conversation ─────────────────────────────────────────────────────────────

# Taille maximale d'un message d'historique : le plafond de génération lui-même,
# LLM_MAX_TOKENS (4096) à ~3,5 caractères/token. Ce dimensionnement sert le
# round-trip et rien d'autre — une réponse que le modèle pouvait légitimement
# produire doit pouvoir revenir dans l'historique au tour suivant, sinon la borne
# casserait la conversation en 422, ce qui serait pire que le défaut corrigé.
#
# Ce que cette borne protège, exactement : la lecture et le parse de la requête.
# PAS le serveur d'inférence — il ne voit jamais plus que ce que `fit_history`
# retient, soit HISTORY_WINDOW_SHARE de la fenêtre de prompt, ~3 600 caractères
# aujourd'hui. Un message de 14 336 caractères est donc accepté puis
# systématiquement écarté du prompt : c'est voulu, refuser vaudrait moins bien
# que tronquer.
MAX_MESSAGE_CHARS = 14_336

# Messages d'historique réellement soumis au LLM. C'est la borne qui compte : le
# budget de contexte en dérive, et l'API ne lit que les derniers.
MAX_HISTORY_MESSAGES = 6

# Messages acceptés dans une requête. L'API n'en garde que les
# MAX_HISTORY_MESSAGES derniers ; cette borne-ci ne protège donc, elle aussi, que
# la taille de la requête : au pire MAX_HISTORY_PAYLOAD × MAX_MESSAGE_CHARS, soit
# ~700 Ko de corps, contre une liste sans borne auparavant. Assez large pour
# qu'un client qui envoie tout son fil de conversation ne soit pas rejeté.
MAX_HISTORY_PAYLOAD = 50


class Message(BaseModel):
    # Recopié tel quel dans le prompt par `_build_messages`. En `str` libre, un
    # client pouvait poster {"role": "system", ...} dans chat_history et glisser
    # un second message système à côté du vrai — celui qui porte « cite chaque
    # affirmation » et « dis-le si tu ne trouves pas ». C'est le défaut que ce
    # budget corrige, par une autre route : la troncature jetait ces règles,
    # une injection de rôle les contredit.
    role: Literal["user", "assistant"]
    # « question » était plafonnée, l'historique non : c'était le vecteur par
    # lequel un prompt dépassait num_ctx, et Ollama le tronquait par le début.
    content: str = Field(..., max_length=MAX_MESSAGE_CHARS)


# ─── Retrieval ────────────────────────────────────────────────────────────────

class ChunkResult(BaseModel):
    chunk_id: str
    element_id: str
    graph_node_id: str
    document: str                     # texte du chunk
    filename: str                     # nom du fichier seul (le chapitre)
    # L'ingestion distingue le chapitre de l'ouvrage : deux livres peuvent
    # contenir une « Préface ». C'est source_path qui identifie un document,
    # jamais filename seul (cf. DocumentIdentity côté ingestion).
    collection: str = ""              # ouvrage / dossier de premier niveau
    source_path: str = ""             # chemin relatif complet — identité réelle
    section_title: str = ""           # titre de la section porteuse
    # Langue du document (ISO 639-1), vide si indéterminée. Le corpus est mixte :
    # c'est ce qui permet d'annoncer la langue d'une source à l'utilisateur.
    language: str = ""
    # Profondeur du titre porteur dans la hiérarchie (0 = titre de tête).
    depth: int = 0
    page_no: int
    label: str                        # paragraph, section_header, table, picture…
    minio_url: str | None = None
    page_position: int = 0
    ref_position: int = 0
    distance: float                   # distance cosine ChromaDB
    rerank_score: float | None = None  # logit brut du cross-encoder (non borné)
    # Sigmoïde du logit, dans [0, 1]. Le cross-encoder ms-marco sort des logits
    # (typiquement -11..+11) : les afficher tels quels comme une similarité
    # induit l'utilisateur en erreur au moment où il arbitre les sources.
    relevance: float | None = None
    # Score Reciprocal Rank Fusion quand la recherche hybride est active.
    # Sur une autre échelle que distance et rerank_score : ne pas les mélanger.
    fusion_score: float | None = None

    @property
    def document_key(self) -> str:
        """Identité du document : le chemin, avec repli sur le nom de fichier."""
        return self.source_path or self.filename


class SearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # None = la valeur configurée (RETRIEVAL_TOP_K). Un défaut chiffré ici
    # écrasait le réglage sans que rien ne le signale : le service était réglé
    # sur 50 candidats et en recevait 20, parce que le client n'avait rien
    # demandé.
    top_k: int | None = Field(default=None, ge=1, le=200)
    # Historique de conversation (multi-turn) — utilisé par /chat/start,
    # ignoré par /search et /sources.
    chat_history: list[Message] = Field(
        default_factory=list, max_length=MAX_HISTORY_PAYLOAD
    )


class SearchResponse(BaseModel):
    question: str
    chunks: list[ChunkResult]


# ─── Reranking & sélection sources ────────────────────────────────────────────

class SourceGroup(BaseModel):
    filename: str                     # nom du chapitre
    collection: str = ""              # ouvrage dont il fait partie
    source_path: str = ""             # identité du document (clé de groupement)
    best_score: float                 # meilleur rerank_score (logit) du groupe
    best_relevance: float = 0.0       # meilleure pertinence dans [0, 1]
    chunks: list[ChunkResult]

    @property
    def display_name(self) -> str:
        """Libellé lisible : « Ouvrage > Chapitre », ou le chapitre seul."""
        return f"{self.collection} > {self.filename}" if self.collection else self.filename


class SourcesResponse(BaseModel):
    question: str
    groups: list[SourceGroup]         # groupés par document, triés par best_score


class SourceSelectionRequest(BaseModel):
    thread_id: str
    # Ignoré : la question vit dans l'état checkpointé sous `thread_id`. Le
    # champ reste accepté pour ne pas casser les clients existants, mais il ne
    # décrit aucun contrat — le renseigner ne change rien à la réponse.
    question: str = ""
    selected_element_ids: list[ElementId] = Field(..., min_length=1)
    stream: bool = True


# ─── Graph context ────────────────────────────────────────────────────────────

class BreadcrumbEntry(BaseModel):
    node_id: str
    label: str
    text: str


class SectionElement(BaseModel):
    node_id: str
    label: str
    text: str
    minio_url: str | None = None
    sequence: int
    page_no: int = 0
    # Légende rattachée à une image ou un tableau, via l'arête DESCRIBES du
    # graphe. Sans elle le LLM ne voit qu'un [img:ID] muet et ne peut pas
    # juger si l'illustration sert la réponse.
    caption: str = ""


class SectionContext(BaseModel):
    element_id: str
    section_id: str
    breadcrumbs: list[BreadcrumbEntry]   # du Document jusqu'à la section
    elements: list[SectionElement]       # enfants ordonnés par sequence
    markdown: str                         # contexte assemblé prêt pour le LLM
    # Résolus pendant la remontée du graphe. Extraits ici plutôt que devinés
    # depuis les breadcrumbs par les appelants : le post-processing des
    # citations en dépend, et une heuristique sur `label` y était fausse.
    filename: str = ""                    # nom du document porteur
    collection: str = ""                  # ouvrage dont il fait partie
    section_title: str = ""               # titre de la section
    # Queue de la section précédente et tête de la suivante : le « avant /
    # après » demandé au produit. Les sections sont frères sous le Document,
    # ordonnées par la propriété `sequence` de l'arête PARENT_OF.
    before: list[SectionElement] = Field(default_factory=list)
    after: list[SectionElement] = Field(default_factory=list)
    before_title: str = ""
    after_title: str = ""
    truncated: bool = False               # la fenêtre a-t-elle écarté des éléments ?


# ─── Chat / génération ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    selected_element_ids: list[ElementId] = Field(default_factory=list)
    chat_history: list[Message] = Field(
        default_factory=list, max_length=MAX_HISTORY_PAYLOAD
    )
    stream: bool = True


class Citation(BaseModel):
    element_id: str
    filename: str
    collection: str = ""              # ouvrage, quand le document en fait partie
    section_title: str = ""           # section d'où provient l'affirmation
    page_no: int
    text_excerpt: str

    @property
    def label(self) -> str:
        """Référence lisible : « Ouvrage > Chapitre, p.42, § Titre »."""
        parts = [f"{self.collection} > {self.filename}" if self.collection else self.filename]
        if self.page_no:
            parts.append(f"p.{self.page_no}")
        if self.section_title:
            parts.append(f"§ {self.section_title}")
        return ", ".join(p for p in parts if p)


class ImageRef(BaseModel):
    element_id: str
    minio_url: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    images: list[ImageRef]
    search_count: int
    # Renseigné par /chat/simple, seule route qui crée un thread_id que
    # l'appelant ne connaît pas. Sans lui, une génération directe ne peut
    # jamais être notée par /feedback : l'interaction est enregistrée, et
    # l'usage « jeu doré réel » l'exclut en silence. /chat/resume le laisse
    # vide — son appelant vient de le fournir.
    thread_id: str = ""


class AnswerRequest(BaseModel):
    """Question posée sans sélection humaine des sources."""

    question: str = Field(..., min_length=1, max_length=2000)
    # None = la valeur configurée (RETRIEVAL_TOP_K).
    top_k: int | None = Field(default=None, ge=1, le=200)
    chat_history: list[Message] = Field(
        default_factory=list, max_length=MAX_HISTORY_PAYLOAD
    )
    # Nombre de sources reconstruites. Laissé à None, AUTO_SELECT_TOP_K s'applique.
    max_sources: int | None = Field(default=None, ge=1, le=20)


class RetrievedContext(BaseModel):
    """Un passage effectivement soumis au LLM, tel qu'un évaluateur le lit."""

    element_id: str
    section_id: str
    filename: str
    collection: str = ""
    source_path: str = ""
    section_title: str = ""
    language: str = ""
    page_no: int = 0
    relevance: float | None = None
    text: str


class AnswerResponse(BaseModel):
    """Réponse complète et traçable : ce qui a été lu, ce qui a été cité, à quel coût.

    Les contextes sont indispensables à l'évaluation : sans eux, impossible de
    distinguer un échec de recherche d'un échec de génération.
    """

    question: str
    answer: str
    # Éléments distincts remontés par la recherche, du mieux au moins bien
    # classé. Distinguer ce que la RECHERCHE a trouvé de ce qui a atteint le
    # LLM est ce qui permet d'attribuer la faute : un passage trouvé puis
    # écarté avant la génération n'est pas le même échec qu'un passage jamais
    # trouvé.
    retrieved_element_ids: list[str] = Field(default_factory=list)
    contexts: list[RetrievedContext]
    citations: list[Citation]
    images: list[ImageRef]
    search_count: int
    retrieval_ms: int
    generation_ms: int
    dropped_contexts: int = 0     # sources écartées faute de place dans la fenêtre


# ─── Capture d'usage ──────────────────────────────────────────────────────────

class UsageStats(BaseModel):
    """Taille de l'actif constitué par la capture.

    Aucune purge n'existe : c'est un jeu de données, pas un cache. La
    contrepartie est que sa taille doit être visible — un actif qui grossit
    sans qu'on le sache redevient une fuite.
    """

    enabled: bool
    path: str
    interactions: int
    sources: int
    size_bytes: int
    # Échecs de capture depuis le démarrage. Non nul = des interactions ont été
    # servies sans être enregistrées ; le journal en porte la cause.
    failures: int = 0


class FeedbackRequest(BaseModel):
    """Appréciation d'une réponse par la personne qui l'a lue."""

    thread_id: str = Field(..., min_length=1, max_length=64)
    # Binaire, pas une échelle : personne ne remplit une échelle, et un 3/5 ne
    # se lit pas. Deux valeurs se comptent.
    rating: Literal["utile", "inutile"]
    # Libre et facultatif. Borné comme tout texte venant d'un client : sans
    # borne, le corps d'une requête n'a plus de taille maximale.
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    """`recorded` faux n'est pas une erreur du client : la capture peut être
    désactivée, ou avoir échoué. Le détail le dit."""

    recorded: bool
    detail: str = ""


# ─── Health ───────────────────────────────────────────────────────────────────

class SessionStats(BaseModel):
    """État de la purge des sessions LangGraph, vu de l'extérieur.

    Cette purge a passé toute la vie du projet à échouer en silence pendant que
    le journal annonçait le contraire. Un exploitant doit pouvoir vérifier
    qu'elle tourne sans lire les logs : `purged` qui reste à zéro alors que des
    sessions s'accumulent, ou `failures` non nul, se voient d'un coup d'œil.
    """

    path: str
    # Faux = registre en mémoire (CHECKPOINT_DB_PATH vide) : les sessions ne
    # survivent pas au redémarrage, donc rien n'a à être purgé après lui.
    durable: bool
    # Sessions connues du registre, donc atteignables par la purge.
    live: int
    # Sessions RÉELLEMENT supprimées depuis le démarrage — pas tentées.
    purged: int
    # Suppressions en échec. Non nul = de l'état reste sur le disque ; le
    # journal en porte la cause, et la purge le retentera.
    failures: int = 0


class HealthResponse(BaseModel):
    status: str                       # "ok" | "degraded"
    ollama_model: str
    services: dict[str, bool] = Field(default_factory=dict)
    # Taille de la base de capture. Aucune purge n'existe : un actif qui
    # grossit sans qu'on le sache redevient une fuite, donc la sonde le porte.
    usage: UsageStats | None = None
    # État de la purge des sessions. Même raison, cause inverse : ici une purge
    # EXISTE, et c'est le fait qu'elle aboutisse qui doit être vérifiable.
    sessions: SessionStats | None = None
