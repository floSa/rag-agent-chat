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
    # La même question dans l'autre langue du corpus. N'existe que pour la
    # recherche : la génération ne la voit jamais.
    search_translation: str | None

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

    # Contexte enrichi via NebulaGraph — les sections CANDIDATES.
    enriched_contexts: list[SectionContext]
    # Les sections que le budget de fenêtre a réellement retenues, telles
    # qu'elles sont parties au LLM : tronquées si elles l'ont été. Renseigné par
    # node_generate depuis `on_fit`, comme `dropped_contexts`, et pour la même
    # raison — une métrique de précision du contexte calculée sur les candidates
    # mesure une intention, pas ce qui a été payé en tokens.
    submitted_contexts: list[SectionContext]

    # Réponse générée
    response: str
    citations: list[Citation]
    images: list[ImageRef]

    # Boucle agentique
    search_count: int           # nombre d'itérations de recherche (max 3)
    needs_more_info: bool       # le LLM a-t-il demandé une recherche supplémentaire ?
    next_query: str | None      # sous-question pour la prochaine itération

    # Sources écartées par le budget de fenêtre, renseigné par node_generate.
    # Porté par l'état plutôt que recalculé par /answer : deux calculs séparés
    # dérivent, et c'est ce chiffre que la campagne d'évaluation publie.
    dropped_contexts: int

    # Chronométrage par étage, renseigné par les nœuds. Une latence globale ne
    # dit pas quoi optimiser ; c'est ce que /answer expose à l'évaluation.
    _metadata: dict[str, Any]
