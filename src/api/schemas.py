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
    filename: str
    page_no: int
    label: str                        # paragraph, section_header, table, picture…
    minio_url: str | None = None
    page_position: int = 0
    ref_position: int = 0
    distance: float                   # distance cosine ChromaDB
    rerank_score: float | None = None  # score cross-encoder (None avant reranking)


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
    filename: str
    best_score: float                 # meilleur rerank_score du groupe
    chunks: list[ChunkResult]


class SourcesResponse(BaseModel):
    question: str
    groups: list[SourceGroup]         # groupés par document, triés par best_score


class SourceSelectionRequest(BaseModel):
    thread_id: str
    question: str
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


class SectionContext(BaseModel):
    element_id: str
    section_id: str
    breadcrumbs: list[BreadcrumbEntry]   # du Document jusqu'à la section
    elements: list[SectionElement]       # enfants ordonnés par sequence
    markdown: str                         # contexte assemblé prêt pour le LLM


# ─── Chat / génération ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    selected_element_ids: list[ElementId] = Field(default_factory=list)
    chat_history: list[Message] = Field(default_factory=list)
    stream: bool = True


class Citation(BaseModel):
    element_id: str
    filename: str
    page_no: int
    text_excerpt: str


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
