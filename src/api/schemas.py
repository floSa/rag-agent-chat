from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# Identifiant d'élément : hash sha256 tronqué à 10 caractères produit par
# l'ingestion. Validé strictement car interpolé dans les requêtes nGQL.
ElementId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{10}$")]


# ─── Conversation ─────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str    # "user" | "assistant"
    content: str


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

    @property
    def document_key(self) -> str:
        """Identité du document : le chemin, avec repli sur le nom de fichier."""
        return self.source_path or self.filename


class SearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=20, ge=1, le=50)
    # Historique de conversation (multi-turn) — utilisé par /chat/start,
    # ignoré par /search et /sources.
    chat_history: list[Message] = Field(default_factory=list)


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
    chat_history: list[Message] = Field(default_factory=list)
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


# ─── Health ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str                       # "ok" | "degraded"
    ollama_model: str
    services: dict[str, bool] = Field(default_factory=dict)
