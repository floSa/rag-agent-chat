import logging

from langchain_core.tools import tool

from src.agent.retriever import group_by_document, rerank, retrieve

logger = logging.getLogger(__name__)


@tool
def search_vectors(query: str) -> str:
    """Effectue une nouvelle recherche sémantique dans la base vectorielle.

    Utilise cet outil quand tu as besoin de plus d'informations pour répondre
    à la question de l'utilisateur. Formule une sous-question précise et ciblée.

    Args:
        query: La sous-question ou le sujet précis à rechercher.

    Returns:
        Les chunks les plus pertinents trouvés, sous forme de texte structuré.
    """
    logger.info("Tool search_vectors appelé avec : '%s'", query[:80])

    chunks = retrieve(query)
    ranked = rerank(query, chunks)
    groups = group_by_document(ranked)

    if not groups:
        return "Aucun résultat trouvé pour cette recherche."

    lines: list[str] = [f"Résultats pour : {query}\n"]
    for group in groups[:3]:  # limiter à 3 documents pour économiser le contexte
        lines.append(f"\n## {group.filename} (score: {group.best_score:.3f})")
        for chunk in group.chunks[:3]:
            lines.append(
                f"- [src:{chunk.element_id}] p.{chunk.page_no} : {chunk.document[:200]}"
            )

    return "\n".join(lines)


# Liste des outils disponibles pour le LLM
AGENT_TOOLS = [search_vectors]
