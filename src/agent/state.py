from typing import Any

from typing_extensions import TypedDict

from src.api.schemas import (
    ChunkResult,
    Citation,
    ImageRef,
    Message,
    SectionContext,
)


class AgentState(TypedDict):
    # Entrée
    question: str
    chat_history: list[Message]

    # Retrieval
    retrieved_chunks: list[ChunkResult]
    reranked_chunks: list[ChunkResult]

    # Human-in-the-loop : element_ids sélectionnés par l'utilisateur
    # Vide = pas encore sélectionné ; rempli = validation faite
    selected_element_ids: list[str]

    # Sans sélection humaine (endpoint /answer), nombre de sources reconstruites
    # d'office. None = AUTO_SELECT_TOP_K.
    max_sources: int | None

    # Contexte enrichi via NebulaGraph
    enriched_contexts: list[SectionContext]

    # Réponse générée
    response: str
    citations: list[Citation]
    images: list[ImageRef]

    # Boucle agentique
    search_count: int           # nombre d'itérations de recherche (max 3)
    needs_more_info: bool       # le LLM a-t-il demandé une recherche supplémentaire ?
    next_query: str | None      # sous-question pour la prochaine itération

    # Métadonnées internes
    _metadata: dict[str, Any]
