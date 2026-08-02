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
    # Question rendue autonome par node_rewrite, utilisée pour la recherche.
    # La génération continue de voir `question`, telle que posée.
    search_query: str | None

    # Retrieval
    retrieved_chunks: list[ChunkResult]
    reranked_chunks: list[ChunkResult]

    # Human-in-the-loop : element_ids sélectionnés par l'utilisateur
    # Vide = pas encore sélectionné ; rempli = validation faite
    selected_element_ids: list[str]

    # Sans sélection humaine (endpoint /answer), nombre de sources reconstruites
    # d'office. None = AUTO_SELECT_TOP_K.
    max_sources: int | None
    # Candidats demandés à ChromaDB. None = RETRIEVAL_TOP_K.
    top_k: int | None

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

    # Chronométrage par étage, renseigné par les nœuds. Une latence globale ne
    # dit pas quoi optimiser ; c'est ce que /answer expose à l'évaluation.
    _metadata: dict[str, Any]
