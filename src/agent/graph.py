import logging
import re

from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

from src.agent.graph_context import reconstruct_section
from src.agent.llm import generate_stream
from src.agent.minio_client import to_media_path
from src.agent.retriever import group_by_document, rerank, retrieve
from src.agent.settings import settings
from src.agent.state import AgentState
from src.api.schemas import Citation, ImageRef, SectionContext

logger = logging.getLogger(__name__)


# ─── Nœuds du graphe ─────────────────────────────────────────────────────────

def node_retrieve(state: AgentState) -> dict:
    """Encode la question et récupère les chunks ChromaDB."""
    question = state.get("next_query") or state["question"]
    chunks = retrieve(question)
    logger.info("retrieve: %d chunks pour '%s'", len(chunks), question[:60])
    return {
        "retrieved_chunks": chunks,
        "search_count": state.get("search_count", 0) + 1,
    }


def node_rerank(state: AgentState) -> dict:
    """Applique le cross-encoder et retourne les top-K chunks."""
    question = state.get("next_query") or state["question"]
    ranked = rerank(question, state["retrieved_chunks"])
    logger.info("rerank: %d chunks sélectionnés", len(ranked))
    return {"reranked_chunks": ranked}


def node_await_source_selection(state: AgentState) -> dict:
    """Nœud d'attente — interrompu ici pour human-in-the-loop.

    L'état est retourné inchangé : LangGraph met le graphe en pause
    (interrupt_before=["await_source_selection"]) jusqu'à ce que l'utilisateur
    fournisse `selected_element_ids` via l'API /chat/resume.
    """
    groups = group_by_document(state["reranked_chunks"])
    logger.info(
        "Attente sélection sources — %d groupes, %d chunks au total",
        len(groups),
        sum(len(g.chunks) for g in groups),
    )
    return {}


def node_reconstruct_context(state: AgentState) -> dict:
    """Reconstruit le contexte enrichi pour chaque élément sélectionné.

    Première passe : éléments choisis par l'utilisateur. Itérations suivantes
    (recherche déclenchée par le LLM) : top-3 des nouveaux chunks reranqués,
    ajoutés aux contextes déjà reconstruits — sans repasser par la sélection.
    """
    is_iteration = state.get("search_count", 0) > 1

    if is_iteration:
        element_ids = [c.element_id for c in state["reranked_chunks"][:3]]
        contexts: list[SectionContext] = list(state.get("enriched_contexts") or [])
    else:
        element_ids = state.get("selected_element_ids") or []
        if not element_ids:
            # Fallback : utiliser les top-3 chunks reranqués
            element_ids = [c.element_id for c in state["reranked_chunks"][:3]]
            logger.warning("Aucune source sélectionnée, fallback sur top-3.")
        contexts = []

    seen_sections: set[str] = {c.section_id for c in contexts}

    for eid in element_ids:
        try:
            ctx = reconstruct_section(eid)
            if ctx.section_id not in seen_sections:
                contexts.append(ctx)
                seen_sections.add(ctx.section_id)
        except Exception:
            logger.exception("Erreur reconstruction section pour %s", eid)

    logger.info(
        "reconstruct_context: %d sections uniques (itération=%s)", len(contexts), is_iteration
    )
    return {"enriched_contexts": contexts}


async def node_generate(state: AgentState) -> dict:
    """Appelle le LLM Ollama et génère la réponse.

    Les tokens sont poussés au fil de l'eau dans le stream "custom" de
    LangGraph : consommés par /chat/resume en SSE, ignorés (no-op) lors d'un
    ainvoke classique.
    """
    try:
        writer = get_stream_writer()
    except Exception:
        writer = None

    if writer:
        # Nouvelle génération : le frontend efface l'affichage en cours
        # (utile quand la boucle agentique relance une génération)
        writer({"reset": True})

    parts: list[str] = []
    async for token in generate_stream(
        question=state["question"],
        contexts=state["enriched_contexts"],
        chat_history=state.get("chat_history"),
    ):
        parts.append(token)
        if writer:
            writer({"token": token})

    response = "".join(parts)
    logger.info("generate: réponse de %d caractères", len(response))

    # Détection d'une demande de recherche supplémentaire par le LLM
    # Le LLM peut signaler le besoin via search_vectors(query) dans sa réponse
    needs_more = False
    next_query: str | None = None

    search_match = re.search(r"search_vectors\([\"'](.+?)[\"']\)", response)
    if search_match and state.get("search_count", 0) < settings.max_search_iterations:
        needs_more = True
        next_query = search_match.group(1)
        logger.info("LLM demande une recherche supplémentaire : '%s'", next_query)

    # La syntaxe d'appel d'outil ne doit jamais apparaître dans la réponse finale
    response = re.sub(r"search_vectors\([\"'].+?[\"']\)", "", response).strip()

    return {
        "response": response,
        "needs_more_info": needs_more,
        "next_query": next_query,
    }


def node_postprocess(state: AgentState) -> dict:
    """Extrait les citations [src:ID] et les références images [img:ID]."""
    response = state.get("response", "")
    chunks_map = {c.element_id: c for c in state.get("reranked_chunks", [])}

    # Les [img:ID] référencent surtout des éléments des sections reconstruites,
    # qui ne figurent pas dans les chunks reranqués : on indexe les deux.
    media_map: dict[str, str] = {
        elem.node_id: elem.minio_url
        for ctx in state.get("enriched_contexts", [])
        for elem in ctx.elements
        if elem.minio_url
    }
    for chunk in state.get("reranked_chunks", []):
        if chunk.minio_url:
            media_map.setdefault(chunk.element_id, chunk.minio_url)

    # Citations [src:ELEMENT_ID]
    citations: list[Citation] = []
    for match in re.finditer(r"\[src:([a-f0-9]+)\]", response):
        eid = match.group(1)
        chunk = chunks_map.get(eid)
        if chunk and not any(c.element_id == eid for c in citations):
            citations.append(
                Citation(
                    element_id=eid,
                    filename=chunk.filename,
                    page_no=chunk.page_no,
                    text_excerpt=chunk.document[:150],
                )
            )

    # Images [img:ELEMENT_ID] — servies via le proxy /media de l'API
    # (les URLs internes minio:9000 sont inaccessibles depuis le navigateur)
    images: list[ImageRef] = []
    for match in re.finditer(r"\[img:([a-f0-9]+)\]", response):
        eid = match.group(1)
        minio_url = media_map.get(eid)
        if minio_url and not any(i.element_id == eid for i in images):
            images.append(
                ImageRef(
                    element_id=eid,
                    minio_url=to_media_path(minio_url),
                )
            )

    logger.info("postprocess: %d citations, %d images", len(citations), len(images))
    return {"citations": citations, "images": images}


# ─── Logique de routage conditionnel ─────────────────────────────────────────

def should_search_more(state: AgentState) -> bool:
    return (
        state.get("needs_more_info", False)
        and state.get("search_count", 0) < settings.max_search_iterations
    )


def is_first_pass(state: AgentState) -> bool:
    """Seule la première recherche passe par la sélection utilisateur ;
    les itérations déclenchées par le LLM vont directement à la reconstruction."""
    return state.get("search_count", 0) <= 1


# ─── Construction du graphe ───────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("retrieve", node_retrieve)
    graph.add_node("rerank", node_rerank)
    graph.add_node("await_source_selection", node_await_source_selection)
    graph.add_node("reconstruct_context", node_reconstruct_context)
    graph.add_node("generate", node_generate)
    graph.add_node("postprocess", node_postprocess)

    graph.add_edge("retrieve", "rerank")
    graph.add_conditional_edges(
        "rerank",
        is_first_pass,
        {True: "await_source_selection", False: "reconstruct_context"},
    )
    graph.add_edge("await_source_selection", "reconstruct_context")
    graph.add_edge("reconstruct_context", "generate")
    graph.add_edge("generate", "postprocess")

    graph.add_conditional_edges(
        "postprocess",
        should_search_more,
        {True: "retrieve", False: END},
    )

    graph.set_entry_point("retrieve")
    return graph


# Graphe compilé avec interrupt avant la sélection des sources.
# Le checkpointer est requis par LangGraph pour suspendre/reprendre le flux
# (l'état est persisté par thread_id, cf. /chat/start et /chat/resume).
agent_graph = build_graph().compile(
    checkpointer=MemorySaver(),
    interrupt_before=["await_source_selection"],
)
