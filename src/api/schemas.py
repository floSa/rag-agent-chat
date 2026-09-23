import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from src.agent.settings import settings

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
    # lequel un prompt dépassait num_ctx — et c'est la borne client qui coupe,
    # la fenêtre du serveur étant refusée au-delà, jamais tronquée.
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
    # après » demandé au produit. La section voisine est le frère en-tête sous
    # le PARENT COMMUN — un `Document` ou un autre `SectionHeader` depuis que
    # l'ingestion imbrique les titres — ordonné par la propriété `sequence` de
    # l'arête PARENT_OF. Voir `graph_context._find_sibling` pour ce que cette
    # définition laisse de côté.
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


# Plafond de sources qu'une requête peut demander. DÉRIVÉ, jamais écrit en dur :
# c'est `rerank` qui décide combien d'éléments existent en aval, et le déclarer
# indépendamment est ce qui a produit une borne fausse. Le tenir est l'affaire de
# `tests/unit/test_borne_des_sources.py`, qui confronte cette valeur à ce que la
# chaîne SERT — et non à ce que la configuration DIT.
MAX_SOURCES_SERVIES = settings.rerank_top_k


class AnswerRequest(BaseModel):
    """Question posée sans sélection humaine des sources."""

    question: str = Field(..., min_length=1, max_length=2000)
    # None = la valeur configurée (RETRIEVAL_TOP_K).
    top_k: int | None = Field(default=None, ge=1, le=200)
    chat_history: list[Message] = Field(
        default_factory=list, max_length=MAX_HISTORY_PAYLOAD
    )
    # Nombre de sources reconstruites. Laissé à None, AUTO_SELECT_TOP_K s'applique.
    #
    # LA BORNE N'EST PAS UN CHOIX DE SCHÉMA, C'EST CE QUE LA CHAÎNE SAIT SERVIR,
    # et elle est dérivée pour cette raison. `node_reconstruct_context` découpe
    # `ranking[:max_sources]` sur la liste que `rerank` rend, et `rerank` n'en
    # rend jamais plus de `RERANK_TOP_K`. Écrite en dur à 20 quand le reranker
    # en servait 10, elle promettait 20 sources et en rendait 10 SANS RIEN DIRE :
    # l'appelant ne pouvait pas distinguer « il n'y avait que 10 passages
    # pertinents » de « ta demande a été rabotée ». Un 422 le lui dit.
    #
    # POURQUOI BORNER LA PROMESSE PLUTÔT QU'ÉLARGIR LA CHAÎNE : servir réellement
    # 20 exige de porter `RERANK_TOP_K` à 20, donc de changer la chaîne de TOUS
    # les appels. Mesuré le 23 septembre 2026 sur les 26 questions du jeu de
    # contrôle, ce passage double le contexte soumis — 84,3 → 177,0 éléments au
    # prompt — et ne fait basculer AUCUNE question (rappel au prompt 0,8077
    # inchangé). Le registre le détaille ; le gain de monter ce k y est écrit
    # NON TRANCHÉ faute d'instrument, et un accident d'écriture de schéma n'est
    # pas ce qui doit trancher un réglage de production.
    max_sources: int | None = Field(
        default=None,
        ge=1,
        le=MAX_SOURCES_SERVIES,
        description=(
            "Sources reconstruites pour cette réponse. Le plafond est celui que "
            "la chaîne sert réellement : le reranker ne rend pas plus de "
            "RERANK_TOP_K éléments, et une demande au-delà est refusée (422) "
            "plutôt que rabotée en silence. Laissé vide, AUTO_SELECT_TOP_K "
            "s'applique."
        ),
    )


class RetrievedContext(BaseModel):
    """Une section reconstruite, telle qu'un évaluateur la lit.

    **Toutes ne sont pas parties au LLM.** La liste porte les sections
    CANDIDATES ; `retained` dit lesquelles le budget de fenêtre a effectivement
    retenues. La distinction est la seule qui rende la précision du contexte
    calculable : une section écartée faute de place n'est pas un contexte
    inutile, c'est un contexte NON PAYÉ, et elle ne doit entrer ni au numérateur
    ni au dénominateur.
    """

    element_id: str
    section_id: str
    filename: str
    collection: str = ""
    source_path: str = ""
    section_title: str = ""
    language: str = ""
    page_no: int = 0
    relevance: float | None = None
    # Faux = la section a été reconstruite puis écartée par le budget de
    # fenêtre. Le nombre d'écartées est aussi publié à part
    # (`dropped_contexts`), et les deux doivent s'accorder.
    retained: bool = True
    # Éléments présents dans `text`, marqueurs `[src:ID]` et `[img:ID]` lus dans
    # le texte lui-même. C'est ce qui permet de dire si un élément d'or a atteint
    # le LLM : `element_id` ne nomme que la GRAINE du retrieval, alors que la
    # fenêtre du graphe en ramène jusqu'à treize, plus les voisines.
    element_ids: list[str] = Field(default_factory=list)
    # Retenue, la section telle qu'elle est PARTIE — tronquée si elle l'a été,
    # donc les caractères réellement payés en tokens. Écartée, le contexte
    # reconstruit qui n'a pas été envoyé.
    text: str


class StageTimings(BaseModel):
    """Décomposition du temps d'une réponse, étage par étage.

    **C'est une partition, et l'invariant se lit ici :** la somme des huit
    étages plus `residual_ms` vaut exactement `total_ms`. Sans le résidu, un
    étage non instrumenté disparaîtrait du tableau tout en étant payé ; avec
    lui, le temps que personne ne réclame reste visible — et un résidu large est
    en soi un résultat.

    `total_ms` est mesuré autour de la traversée entière du graphe : c'est le
    seul chiffre qui ne dépend d'aucune instrumentation interne, donc le seul
    contre lequel les étages puissent être confrontés.

    Ne pas confondre avec `AnswerResponse.retrieval_ms`, qui AGRÈGE
    `dense_ms + lexical_ms + fusion_ms + rerank_ms` : l'ajouter à la somme
    doublerait le comptage de toute la recherche.
    """

    # Deux appels LLM distincts : la traduction est un coût de la recherche
    # translingue, la réécriture un coût des questions de suivi.
    rewrite_ms: int = 0
    translation_ms: int = 0
    # Ce que `retrieve` fait, découpé : jusqu'à quatre classements puis la
    # fusion RRF. C'est ce qui rend « dense seul vs hybride » arbitrable au prix.
    dense_ms: int = 0
    lexical_ms: int = 0
    fusion_ms: int = 0
    rerank_ms: int = 0
    # La reconstruction par le graphe — le pari central du projet, et le seul
    # étage qui n'avait jamais été chronométré.
    reconstruction_ms: int = 0
    generation_ms: int = 0
    # Temps mural moins la somme des étages. Peut être NÉGATIF : c'est alors la
    # seule trace observable d'un double comptage, et le borner à zéro
    # effacerait précisément ce qu'on cherche à voir.
    residual_ms: int = 0
    total_ms: int = 0


class GenerationMeasure(BaseModel):
    """Ce que le serveur d'inférence a réellement compté, face à nos estimations.

    `LLM_MAX_TOKENS=4096` confisque la moitié de la fenêtre de 8192 à la
    génération, et rien ne disait qu'elle en avait besoin : `runs/*.json`
    n'enregistrait que `generation_ms`. Ces champs transforment la présomption
    en mesure dès qu'une campagne tourne.
    """

    # Longueur de la réponse APRÈS retrait de la syntaxe d'appel d'outil, donc
    # ce que l'utilisateur lit.
    answer_chars: int = 0
    # Tokens générés, décompte du serveur. `None` = il ne l'a pas rendu ;
    # ce n'est pas zéro, et une moyenne qui les confondrait serait fausse.
    eval_count: int | None = None
    # Tokens du prompt, décompte du serveur.
    prompt_eval_count: int | None = None
    # Notre estimation du même prompt, avec le ratio qui a décidé de la coupe.
    # C'est le seul terme de comparaison qui calibre quelque chose.
    prompt_tokens_estimated: int = 0
    # Faux = `prompt_eval_count` est inexploitable, et le plus souvent parce
    # que le serveur n'a réévalué que le préfixe absent de son cache. La décision
    # d'écarter ces échantillons appartient à `llm.mesure_prompt_exploitable` ;
    # ce champ ne fait que la publier, pour qu'une campagne l'applique au lieu
    # de moyenner à l'aveugle.
    prompt_tokens_reliable: bool = False
    # Le plafond de génération qui s'appliquait (`LLM_MAX_TOKENS` / num_predict).
    # Sans lui, « la génération a-t-elle été coupée ? » n'est pas décidable
    # depuis `eval_count` seul, et c'est toute la question que ce champ sert.
    num_predict: int = 0


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
    # Agrégat historique : recherche + reranking. Conservé tel quel — la capture
    # d'usage a une colonne de ce nom et les campagnes passées le portent — mais
    # ce n'est PAS un étage : `timings` porte la partition.
    retrieval_ms: int
    generation_ms: int
    dropped_contexts: int = 0     # sources écartées faute de place dans la fenêtre
    # Partition exacte du temps, résidu compris.
    timings: StageTimings = Field(default_factory=StageTimings)
    # Ce qu'a coûté la génération en tokens, décompte du serveur d'inférence.
    generation: GenerationMeasure = Field(default_factory=GenerationMeasure)


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


class ReindexResponse(BaseModel):
    """Résultat d'une reconstruction de l'index lexical.

    Le nombre rendu est celui de l'index APRÈS reconstruction : c'est ce que
    l'ingestion peut confronter au nombre de chunks qu'elle vient d'écrire.
    """

    chunks_indexed: int
    # Faux attendu juste après une reconstruction. Vrai signifie que le corpus a
    # encore bougé entre-temps. Un compte de collection ILLISIBLE rend faux, lui
    # aussi, et c'est la décision documentée partout ailleurs : « je ne sais
    # pas » ne doit pas devenir « c'est périmé », sans quoi une panne de Chroma
    # déclencherait des reconstructions en boucle. Ce commentaire annonçait
    # l'inverse du code.
    stale: bool


class EmbeddingModelHealth(BaseModel):
    """Concordance entre le modèle que l'agent LIT et celui qui a INDEXÉ.

    La panne que ce champ rend visible est silencieuse par construction : les
    deux modèles candidats du projet rendent des vecteurs de la même largeur
    (site canonique : `documentation/axes_amelioration.md` §4.4), donc ChromaDB
    accepte l'un pour l'autre et la recherche rend des passages plausibles et
    faux. Aucune sonde de forme ne peut la voir ; seul le NOM discrimine.

    Quatre états, et ils ne se soignent pas pareil :

    - `ok` — l'estampille de la collection est celle du réglage ;
    - `mismatch` — elle en nomme un AUTRE. La recherche est refusée en 503 ;
    - `missing` — la collection ne porte pas d'estampille, donc on ne sait pas
      ce qui l'a produite. Traité comme une divergence, délibérément : un garde
      qui ne comparerait que lorsque l'estampille est présente serait décoratif
      sur exactement le cas où l'on est aveugle ;
    - `unknown` — l'estampille n'a pas pu être lue (store injoignable, ou sonde
      qui n'est pas revenue sous le plafond). « Je n'ai pas pu lire » n'est pas
      « ça diverge » : cet état-là ne dégrade pas le statut à lui seul, la sonde
      `chromadb` de `services` portant déjà ce fait. Ce qui distingue un store
      muet d'une sonde lente est au journal, pas ici : les deux valent « je ne
      sais pas » pour qui lit cette réponse.
    """

    status: str                       # "ok" | "mismatch" | "missing" | "unknown"
    # Ce que le réglage `EMBEDDING_MODEL_NAME` de l'agent nomme.
    expected: str
    # L'estampille lue sur la collection. Nulle quand elle est absente ou
    # illisible — `status` dit lequel des deux.
    collection: str | None = None


class TorchDeviceHealth(BaseModel):
    """Sur quoi les deux modèles de torch calculent, et pourquoi.

    TROIS CONDITIONS INDÉPENDANTES décident qu'un calcul part sur le GPU, et
    chacune suffit à le ramener sur le CPU sans qu'aucune trace ne le dise : le
    build de `torch` embarqué dans l'image, le périphérique donné au conteneur
    par le runtime `nvidia`, et le réglage `TORCH_DEVICE`. Ce champ les publie
    séparément parce qu'elles ne se soignent pas pareil — reconstruire l'image,
    corriger le compose, changer une variable — et qu'un booléen unique
    « gpu: true/false » ne dirait laquelle réparer dans aucun des trois cas.

    `embedding` et `rerank` sont les seuls champs qui disent que le GPU SERT.
    `cuda_available: true` avec `embedding: "cpu"` décrit une carte présente,
    visible, et jamais atteinte ; c'est un état parfaitement possible — il est
    même le DÉFAUT de ce service depuis le 11 septembre 2026 — et c'est
    exactement ce qu'on ne pouvait pas voir avant que le périphérique soit
    explicite.

    Ils valent `null` tant que le modèle concerné n'a pas été chargé : la route
    de santé ne charge rien. Voir `retriever._peripherique_si_charge`.

    Mode d'emploi complet : `documentation/gpu_cuda.md`.
    """

    # Ce que `TORCH_DEVICE` demande — `cpu`, `cuda`, `cuda:1`…
    requested: str
    # Le build de torch, suffixe compris : `2.14.0+cpu` ou `2.14.0+cu130`.
    torch_version: str
    # La version de CUDA avec laquelle torch a été COMPILÉ — `torch.version.cuda`,
    # par exemple `"13.0"` pour une roue `+cu130`. `null` sur une roue `+cpu`, et
    # aucune réservation de GPU ne la fera apparaître : il faut reconstruire
    # l'image. C'est le chiffre qu'on confronte à la version CUDA du PILOTE de
    # l'hôte, celle que `nvidia-smi` affiche en haut à droite.
    #
    # POURQUOI CE CHAMP ET NON `torch.backends.cuda.is_built()`, qui est la
    # forme canonique : cette fonction n'est pas annotée dans torch, et
    # `[tool.mypy] strict = true` refuse un appel non typé. La contourner
    # demanderait de relâcher une règle d'analyse pour un booléen que
    # `torch.version.cuda is not None` rend exactement — annoté `str | None`,
    # `vérifié` le 11 septembre 2026 par `reveal_type`. Le champ dit donc PLUS
    # que le booléen, pour le même fait.
    cuda_build: str | None
    # torch VOIT-il une carte depuis ce processus. C'est le champ qui tombe à
    # faux quand `/dev/nvidia*` manque au conteneur — donc quand la réservation
    # manque au compose — même avec un build CUDA.
    cuda_available: bool
    # Périphérique réellement porté par chaque modèle, `null` s'il n'est pas
    # encore chargé.
    embedding: str | None = None
    rerank: str | None = None
    # POURQUOI CE CHAMP EXISTE : `null` sur `embedding` et `rerank` couvre DEUX
    # états qu'un exploitant ne pouvait pas distinguer — « personne n'a encore eu
    # besoin de ce modèle » et « chaque chargement LÈVE depuis le démarrage, donc
    # le cache ne se peuplera jamais ». `mesuré` le 14 septembre 2026 par l'audit
    # du lot 11 : sur un service dont toute recherche rendait **500**, `/health`
    # publiait EXACTEMENT le même corps au repos et après trois chargements qui
    # avaient levé, et rendait `status: ok`.
    #
    # Ce champ porte le MOTIF, en clair, ou `null` quand aucun motif n'a été
    # trouvé. Il est ce qui fait dégrader `status` — voir `main.health` — et il
    # est ce qu'un exploitant lit pour savoir quoi réparer.
    #
    # `null` NE VEUT PAS DIRE « tout va bien » DANS TOUS LES CAS. Il veut dire
    # « la sonde n'a trouvé aucun motif », et le repli `main._peripherique_inconnu`
    # le porte aussi alors qu'il n'a rien sondé : c'est `torch_version: ""` qui
    # sépare les deux, et c'est pourquoi le statut se lit sur le RÉSULTAT de la
    # sonde et jamais sur le repli.
    #
    # CE QUE CE CHAMP NE COUVRE PAS, et la borne est celle de la route : `/health`
    # NE CHARGE RIEN, donc il ne peut pas voir venir une levée qui ne tient pas à
    # l'EXISTENCE du périphérique — mémoire insuffisante sur la carte, modèle
    # absent du cache HuggingFace, droits refusés dessus. Ces pannes-là rendent
    # toujours 500 sous un `status: ok`. Ce qui est connaissable sans charger,
    # c'est que le périphérique demandé n'existe pas d'ici, et c'est exactement
    # ce que ce champ dit.
    hors_d_atteinte: str | None = None
    # ─── CE QUE CET AGENT PREND SUR LA CARTE, ET CE QUI LE PLAFONNE ──────────
    #
    # CES DEUX CHAMPS EXISTENT POUR UN LECTEUR QUI N'EST PAS DANS CE DÉPÔT : le
    # voisin de carte, qui doit dimensionner son `--gpu-memory-utilization`
    # AVANT de lancer vLLM, puisque c'est une option de lancement. *Il ne doit
    # pas avoir à croire ce dépôt sur parole : il doit pouvoir le lire.*
    #
    # `concurrence_max` — la borne du sémaphore des deux étages torch. C'est la
    # variable dont l'empreinte dépend, et sans elle le pic ci-dessous ne serait
    # qu'un relevé sans garantie de ne pas être dépassé.
    concurrence_max: int = 0
    # `pic_memoire_reservee_mio` — `torch.cuda.max_memory_reserved()`, en Mio.
    #
    # ⚠ **C'EST UN MAXIMUM HISTORIQUE, PAS UNE CONSOMMATION COURANTE.**
    # L'allocateur de torch ne rend rien : cette valeur est un **cliquet**, elle
    # monte et ne redescend jamais. `mesuré` sur le service en production le
    # 14 septembre 2026 : 1 294 Mio à 09:08 UTC, 1 984 à 09:28, même PID, aucun
    # redémarrage entre les deux.
    #
    # `null` TANT QU'AUCUN MODÈLE N'EST CHARGÉ — et c'est la même décision que
    # pour `embedding`/`rerank` : la route ne charge rien, un `0.0` au repos se
    # lirait « cet agent ne prend rien » quand il veut dire « on ne sait pas
    # encore ». Un voisin qui dimensionnerait sur ce zéro prendrait 1,3 Go de
    # trop et ferait tomber cet agent plus tard — §4.50.
    #
    # ⚠ **CE CHAMP SOUS-ESTIME CE QUE `nvidia-smi` ATTRIBUE AU PROCESSUS**, et
    # l'écart est le CONTEXTE CUDA, que torch ne compte pas. `mesuré` le
    # 14 septembre 2026 à 09:34 UTC sur un jumeau `--gpus all`, les deux modèles
    # chargés : ce champ rend **1 036,0 Mio** quand `nvidia-smi` attribue
    # **1 262 MiB** au même PID — **226 MiB d'écart**. Un voisin qui réserverait
    # sur ce seul chiffre sous-réserverait d'autant. *Le chiffre de réservation
    # du §4.51 est donc dérivé des paliers `nvidia-smi`, pas de ce champ ; ce
    # champ sert à VÉRIFIER de l'extérieur que la borne tient, pas à dimensionner.*
    pic_memoire_reservee_mio: float | None = None


class MoteurLlmHealth(BaseModel):
    """QUEL moteur a réellement généré, relevé DU SERVEUR et non du réglage.

    POURQUOI CE CHAMP EXISTE. `llm_model` publie `settings.llm_model` : c'est le
    nom qu'on DEMANDE, et il reste identique quand le serveur d'en face est
    remplacé, mis à jour, ou sert un autre poids sous le même nom. Le banc
    go/no-go du 15 septembre 2026 (§7) a buté dessus : aucune campagne de `runs/`
    ne dit quel moteur l'a produite, donc aucune n'est comparable à une campagne
    d'après une bascule. Ce champ est ce qui manque.

    LE FAIT, JAMAIS L'INTENTION, et c'est la leçon de `TorchDeviceHealth` — dont
    `requested` est le réglage et `embedding` le fait. Ici : `serveur`, `version`,
    `modele_servi` et `fenetre_servie` sont LUS du serveur qui répond.
    `modele_demande` et `options` sont notre réglage, et ils sont nommés à part
    pour qu'on ne les confonde jamais.

    DEUX CHAMPS ONT ÉTÉ RETIRÉS AU LOT 28 — `empreinte_du_modele` et
    `quantification`. Ils n'étaient renseignés que par le catalogue de l'ancien
    moteur ; sous celui-ci ils étaient **structurellement nuls**, ce que ce
    fichier écrivait déjà. Un champ publié qui ne peut plus QUE valoir `null`
    promet une capacité qu'on n'a pas. Ce que leur retrait ne change pas : la
    question du POIDS reste ouverte, et elle est écrite au site de
    `main._le_serveur_sert_ce_que_nous_demandons`. Ce qu'il change pour une
    campagne archivée qui les porte : rien — `evaluate.signature_du_moteur` sait
    toujours les LIRE, et c'est dit à son site.

    `None` SUR LE CHAMP ENTIER SE LIT « JE N'AI PAS PU LIRE », jamais un nom de
    moteur. Un serveur injoignable, une URL mal formée, une réponse qui n'est pas
    du JSON disent tous la même chose ici, et l'ignorance ne s'affirme pas en
    moteur.

    Mode d'emploi complet : `documentation/moteur_llm.md`.
    """

    # `"vllm"`, DÉDUIT DE CE QUI RÉPOND et non d'un réglage : `GET /version` rend
    # 200 et un `version` (`mesuré` le 18 septembre 2026 à 12:35 UTC :
    # `{"version":"0.28.0"}`). `null` quand la route n'a pas répondu — et ce
    # `null` ne nomme PAS ce qu'il y avait en face : le dépôt ne supporte plus
    # qu'un moteur, il ne sait donc plus reconnaître les autres, seulement dire
    # que ce n'est pas celui-là.
    serveur: str | None = None
    # L'URL RÉELLEMENT JOINTE, expurgée : schéma, hôte, port, rien d'autre. Un
    # `null` dit que la route de version n'a pas répondu — donc que ce qui suit
    # est muet, pas que l'adresse manque.
    #
    # EXPURGÉE PARCE QUE CE DÉPÔT EST PUBLIC ET QUE `runs/*.json` Y EST
    # VERSIONNÉ : un déploiement qui mettrait des identifiants dans l'URL les
    # verrait sinon recopiés dans une campagne commitée. Voir
    # `main._endpoint_expurge`.
    endpoint: str | None = None
    # La version du serveur, telle QU'IL la donne — `"0.28.0"`.
    version: str | None = None
    # Le nom qu'on DEMANDE (`settings.llm_model`). C'est le réglage, et il est
    # ici pour une seule raison : confronté à `modele_servi`, il montre le cas où
    # le serveur ne porte PAS ce qu'on lui réclame.
    modele_demande: str
    # Ce que le serveur SERT, confronté à ce que nous demandons.
    #
    # `null` VEUT DIRE « le serveur ne sert pas ce que nous demandons » DEPUIS LE
    # 15 SEPTEMBRE 2026 — non bloquante §2 de l'audit du même jour. Ce champ
    # valait `entrees[0]["id"]`, **quel que soit** cet `id` : jamais confronté à
    # ce que nous demandons, il ne pouvait être nul que sur un catalogue vide, et
    # un serveur servant le modèle d'une autre équipe était donc publié — puis
    # mémorisé à vie — sous un nom faux. La relation qui les confronte est
    # `main._le_serveur_sert_ce_que_nous_demandons`, et elle porte ce qu'elle
    # ferme et ce qu'elle laisse ouvert.
    modele_servi: str | None = None
    # LA QUESTION DU POIDS RESTE OUVERTE, ET ELLE N'A PLUS DE CHAMP — lot 28.
    # `empreinte_du_modele` et `quantification` vivaient ici et n'étaient
    # renseignés que par le catalogue de l'ancien moteur. Ce que l'instance de ce
    # poste expose a été relevé en lecture seule le 15 septembre 2026 à 17:31
    # UTC, sur ses **sept** routes GET (`/openapi.json`) : rien n'y distingue
    # deux poids servis sous un même `id`. `/v1/models` porte `id`, `root`,
    # `max_model_len` — et deux faux amis, `created` et `permission[].id`, qui
    # sont **régénérés à chaque requête** (`created` mesuré à 17:30:51 puis
    # 17:31:05 sur deux lectures du même serveur) : les relever ferait différer
    # deux relevés du même moteur, ce qu'un test interdit désormais. `/metrics`
    # porte la configuration du moteur, dont son utilisation mémoire GPU, mais
    # aucune empreinte de poids — et la lire coûterait une requête de plus par
    # battement sur un serveur partagé.
    #
    # CONSÉQUENCE, écrite au §6 de `documentation/moteur_llm.md` : la position
    # `DIFFÉRENT` de `--compare` est **inatteignable sur deux poids servis sous
    # le même `id`**. Ce qui reste visible est le NOM, qui porte la
    # quantification sur cette instance, et la FENÊTRE servie.
    # `max_model_len` côté vLLM — la fenêtre que le SERVEUR sert, à ne pas
    # confondre avec `options.num_ctx`, qui est celle que NOUS demandons. Les
    # deux ont dérivé sur cette instance : 32768 servie, 8192 demandée.
    #
    # ELLE EST DANS LA SIGNATURE DE `--compare` DEPUIS LE 15 SEPTEMBRE 2026 — non
    # bloquante §4 de l'audit du même jour, où **32 768 contre 8 192 signaient
    # `IDENTIQUE`**. Elle était relevée et publiée, et la comparaison appariée ne
    # s'en servait pas. C'est, avec le NOM servi, le seul fait relevé du serveur
    # qui sépare deux campagnes. Elle satisfait le critère écrit au site
    # de `signature_du_moteur` — invariante pour un moteur donné, elle ne bouge
    # qu'au relancement du serveur avec un autre `--max-model-len` : `mesuré`
    # stable sur deux lectures à 449 s d'écart le 15 septembre 2026, quand
    # `created` changeait dans le même intervalle. `null` quand l'entrée du
    # catalogue ne la porte pas ; elle n'est alors pas imprimée du tout.
    fenetre_servie: int | None = None
    # NOS drapeaux d'appel, ceux qui changent le SENS de la réponse et non sa
    # vitesse. Ils sont du réglage, assumé comme tel : deux campagnes lancées
    # contre le même serveur avec `thinking` dans deux positions ne mesurent pas
    # la même chose, et rien au monde ne le relève du serveur.
    options: dict[str, Any] = Field(default_factory=dict)
    # QUAND ce relevé a été pris, en ISO-8601 UTC à la seconde. `null` seulement
    # sur une campagne écrite par un agent antérieur au 15 septembre 2026.
    #
    # POURQUOI UNE DATE SUR CE CHAMP ET SUR AUCUN AUTRE — non bloquante §3 de
    # l'audit du 15 septembre 2026. Ce relevé est le SEUL état de `/health`
    # mémorisé pour la vie du processus : toutes les autres sondes sont
    # relancées à chaque battement, et ce qu'elles publient date donc de la
    # réponse qu'on lit. Celui-ci peut dater d'il y a onze heures, et rien ne le
    # disait. Le lecteur visé est EXTERNE — le pipeline, l'équipe voisine qui
    # relance son serveur vLLM quand elle change son réglage de mémoire GPU : la
    # valeur devient fausse sans que rien ne rougisse, et la seule défense
    # honnête est de dater ce qu'on publie plutôt que de prétendre qu'il est
    # frais.
    #
    # C'EST LA DATE DU RELEVÉ, JAMAIS CELLE DE LA LECTURE, et la distinction est
    # tout l'intérêt du champ : le rafraîchir à chaque lecture rendrait un relevé
    # de onze heures indiscernable d'un relevé neuf — le défaut exact qu'il
    # ferme. Un test le tient dans les deux directions.
    releve_le: str | None = None


class CodeServiHealth(BaseModel):
    """QUEL CODE TOURNE, relevé DU BUILD et non d'une constante écrite à la main.

    CE CHAMP EST LA RÉPONSE À LA QUESTION QUE DOUZE LOTS N'ONT PAS PU POSER.
    L'agent en service a exécuté du code antérieur pendant douze lots sans que
    rien ne le dise, parce que `/health` publiait l'état de tout SAUF de
    lui-même — ni sha, ni version, ni date de construction (§4.42 du registre).
    Le mécanisme est décrit dans `src/api/identite_du_code.py` ; ce qui suit est
    son CONTRAT, et le contrat est ce qui empêche une image anonyme de passer
    pour identifiée.

    `etat` RÉPOND À UNE SEULE QUESTION — *puis-je me fier à `sha` pour dire quel
    code tourne ?* — et c'est pourquoi il a trois positions et non deux :

    - `identifie` : oui. Sha gravé au build, arbre de construction propre.
    - `arbre_sale` : non, et on sait pourquoi. Le sha est là, mais l'arbre
      portait des modifications non commitées : **le commit nommé ne contient
      pas ce qui tourne.** Un sha publié sans cette réserve serait CRU, ce qui
      est pire que l'anonymat.
    - `anonyme` : non, et rien n'est publié. `sha` y est nécessairement nul.

    LES INVARIANTS SONT TENUS PAR LE VALIDATEUR, PAS PAR LA POLITESSE DES
    APPELANTS, et c'est tout l'objet de ce modèle. Une image anonyme qui se
    présenterait avec un sha, ou un `etat: "identifie"` sans sha, LÈVE à la
    construction — donc aussi à la lecture d'un corps de `/health` venu d'un
    autre agent, puisque c'est le même modèle qui valide dans les deux sens.
    Sans ce validateur, un appelant distrait pourrait fabriquer les deux états
    incohérents, et un lecteur qui teste `if sha:` croirait l'image identifiée.

    `construite_le` VIT HORS DE L'INVARIANT, et délibérément : il est la seule
    chose qu'une image anonyme peut encore porter honnêtement, et il vaut mieux
    que rien quand il faut retrouver quelle construction tourne.
    """

    etat: Literal["identifie", "arbre_sale", "anonyme"]
    # Le sha COMPLET du commit, 40 hexadécimaux minuscules, ou `null`. Complet et
    # non abrégé : ce dépôt porte 448 commits aujourd'hui et en portera plus, et
    # un sha court est une identité qui peut cesser d'être unique — alors qu'il
    # coûte la même chose à écrire. Le tronquer pour l'affichage est le travail
    # du lecteur, jamais celui du champ.
    sha: str | None = None
    # QUAND l'image a été construite, en ISO-8601 UTC. Il ne remplace pas le sha
    # et ne prétend pas à l'exactitude d'un verrou : deux images du même sha à
    # deux mois d'écart n'embarquent pas les mêmes roues, et c'est le seul fait
    # publié ici qui permette de les séparer.
    construite_le: str | None = None
    # POURQUOI on ne peut pas se fier au sha, en clair, ou `null` quand on le
    # peut. Un code d'état que personne ne sait interpréter est un code que
    # personne ne lit : les trois chemins vers `anonyme` ne se soignent pas
    # pareil — rien de gravé, un relevé qui a échoué, un build à moitié
    # instrumenté — et seule cette phrase les distingue.
    avertissement: str | None = None

    @model_validator(mode="after")
    def _l_anonymat_ne_se_negocie_pas(self) -> "CodeServiHealth":
        """Les trois invariants du contrat, et ce que chacun ferme.

        Ils sont écrits ici plutôt que confiés au constructeur parce que ce
        modèle valide AUSSI ce qui arrive du dehors : `scripts/evaluate.py` et
        le pipeline d'ingestion lisent `/health` d'un agent qu'ils n'ont pas
        construit, et un agent trafiqué ou à moitié déployé ne doit pas pouvoir
        leur faire croire à une identité.
        """
        if (self.sha is None) != (self.etat == "anonyme"):
            raise ValueError(
                "identité de code incohérente : `sha` nul et `etat` autre "
                "qu'`anonyme`, ou l'inverse. Une image sans sha est anonyme, et "
                "une image anonyme ne publie pas de sha — c'est la borne que ce "
                "modèle existe pour tenir."
            )
        if (self.avertissement is None) != (self.etat == "identifie"):
            raise ValueError(
                "identité de code incohérente : tout état autre qu'`identifie` "
                "doit dire POURQUOI on ne peut pas se fier au sha, et "
                "`identifie` ne s'assortit d'aucune réserve."
            )
        if self.sha is not None and not re.fullmatch(r"[0-9a-f]{40}", self.sha):
            raise ValueError(
                f"`sha` n'est pas un sha de commit : {self.sha!r}. Attendu 40 "
                "caractères hexadécimaux minuscules — une chaîne vide, un sha "
                "abrégé ou un `unknown` passeraient pour une identité auprès "
                "d'un lecteur pressé."
            )
        return self


class HealthResponse(BaseModel):
    """Ce que `/health` publie, et DEUX CLÉS ONT CHANGÉ DE NOM AU LOT 28.

    Le champ qui publie le modèle demandé s'appelle désormais `llm_model`, et la
    sonde publiée sous `services` a pris le nom `llm`. Les deux portaient le nom
    d'un moteur que ce dépôt ne sert plus, et une clé qui nomme faux renseigne
    faux.

    C'EST UNE RUPTURE DE CONTRAT, ET ELLE EST ASSUMÉE PLUTÔT QUE TUE. Ce qui la
    borne, `mesuré` le 18 septembre 2026 par `git grep` sur ce dépôt : le
    healthcheck de `docker-compose.yml` ne lit aucune des deux clés — il ne lit
    que le code HTTP —, et le dépôt ne contient aucun autre lecteur. Ce qui n'est
    PAS borné : un lecteur hors dépôt — le pipeline voisin, un tableau de bord —
    lirait `KeyError` ou `null`. La rupture est annoncée avec la migration du
    `.env` dans `documentation/moteur_llm.md`, qui est le document que le pilote
    joue avant de redéployer.
    """

    status: str                       # "ok" | "degraded"
    llm_model: str
    services: dict[str, bool] = Field(default_factory=dict)
    # Sondes qui n'ont pas répondu avant le plafond de /health. Elles valent
    # `false` dans `services`, et ce n'est pas une approximation : le healthcheck
    # comme l'exploitant ne doivent jamais lire « je n'ai pas eu le temps de
    # regarder » comme « ça répond ». Mais les deux ne se soignent pas pareil —
    # une panne est un fait sur le service, une sonde non revenue un fait sur
    # l'agent — donc la distinction existe ici, à côté du contrat plutôt que
    # dedans : élargir `services` en `dict[str, bool | None]` aurait imposé le
    # doute à tous ses lecteurs pour un cas qui est normalement vide.
    services_unknown: list[str] = Field(default_factory=list)
    # Taille de la base de capture. Aucune purge n'existe : un actif qui
    # grossit sans qu'on le sache redevient une fuite, donc la sonde le porte.
    usage: UsageStats | None = None
    # État de la purge des sessions. Même raison, cause inverse : ici une purge
    # EXISTE, et c'est le fait qu'elle aboutisse qui doit être vérifiable.
    sessions: SessionStats | None = None
    # Concordance du modèle d'embedding. Ce champ n'est PAS optionnel, et c'est
    # la différence avec les deux précédents : leur absence est une information
    # sur un accessoire, tandis qu'une réponse muette sur la concordance se lit
    # comme une réponse rassurante. L'inconnu a donc un nom — `unknown` — plutôt
    # qu'un null.
    embedding_model: EmbeddingModelHealth
    # Périphérique de torch. Non optionnel pour la MÊME raison que le champ
    # ci-dessus : une réponse muette sur le périphérique se lirait comme une
    # réponse rassurante, et ce champ existe précisément pour qu'on cesse de
    # deviner sur quoi ce service calcule.
    torch_device: TorchDeviceHealth
    # Quel moteur a généré. OPTIONNEL, et c'est la différence avec les deux
    # champs ci-dessus : leur muet se lirait comme une réponse rassurante, alors
    # qu'ici `null` est la seule réponse honnête quand le serveur n'a pas
    # répondu — et un agent ANTÉRIEUR à ce lot ne publie pas la clé du tout.
    # `scripts/evaluate.py` distingue les deux cas de la même façon : muet.
    moteur_llm: MoteurLlmHealth | None = None
    # QUEL CODE TOURNE. NON OPTIONNEL, pour la MÊME raison que `embedding_model`
    # et `torch_device` : une réponse muette sur l'identité du code se lit comme
    # une réponse rassurante, et c'est exactement la lecture qui a laissé douze
    # lots croire qu'ils mesuraient les gardes qu'ils venaient de livrer. Le
    # non-savoir a donc un nom — `anonyme` — plutôt qu'un null.
    #
    # ET LA DISTINCTION AVEC UN AGENT ANTÉRIEUR EST À LA CHARGE DU LECTEUR, non
    # de ce champ : un agent d'avant ce lot ne publie pas la clé du tout, ce qui
    # se lit `absente` là où un agent d'après publie au moins `anonyme`. Les deux
    # veulent dire « je ne sais pas quel code tourne » ; seule la seconde prouve
    # qu'on a posé la question.
    code_servi: CodeServiHealth
