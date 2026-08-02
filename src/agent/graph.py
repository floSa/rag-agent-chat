import logging
import re
import time
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

from src.agent.graph_context import reconstruct_section
from src.agent.llm import generate_stream, rewrite_question, translate_question
from src.agent.minio_client import to_media_path
from src.agent.retriever import group_by_document, rerank, retrieve
from src.agent.settings import settings
from src.agent.state import AgentState
from src.api.schemas import ChunkResult, Citation, ImageRef, SectionContext

logger = logging.getLogger(__name__)


# ─── Nœuds du graphe ─────────────────────────────────────────────────────────

async def node_rewrite(state: AgentState) -> dict[str, Any]:
    """Rend la question autonome avant de l'encoder.

    Sans historique, ou si la question a déjà été réécrite par l'appelant, le
    nœud ne fait rien et n'appelle pas le LLM.
    """
    if state.get("search_query"):
        return {}
    rewritten = await rewrite_question(state["question"], state.get("chat_history"))
    # La traduction porte sur la question REÉCRITE : traduire « et pour les
    # femmes ? » ne donnerait rien de plus utile en anglais qu'en français.
    translation = await translate_question(rewritten)
    return {"search_query": rewritten, "search_translation": translation}


def _search_query(state: AgentState) -> str:
    """Requête effectivement envoyée à la recherche.

    Priorité à la sous-question demandée par le LLM (boucle agentique), puis à
    la question réécrite, puis à la question d'origine.
    """
    return state.get("next_query") or state.get("search_query") or state["question"]


def node_retrieve(state: AgentState) -> dict[str, Any]:
    """Encode la question et récupère les chunks ChromaDB."""
    question = _search_query(state)
    started = time.monotonic()
    # La boucle agentique cherche une sous-question précise fournie par le
    # modèle : elle n'a pas de traduction, et n'en a pas besoin.
    translation = None if state.get("next_query") else state.get("search_translation")
    chunks = retrieve(question, top_k=state.get("top_k"), translation=translation)
    elapsed = int((time.monotonic() - started) * 1000)
    logger.info("retrieve: %d chunks en %d ms pour '%s'", len(chunks), elapsed, question[:60])
    metadata = dict(state.get("_metadata") or {})
    metadata["retrieval_ms"] = metadata.get("retrieval_ms", 0) + elapsed
    return {
        "retrieved_chunks": chunks,
        "search_count": state.get("search_count", 0) + 1,
        "_metadata": metadata,
    }


def node_rerank(state: AgentState) -> dict[str, Any]:
    """Applique le cross-encoder et retourne les top-K chunks."""
    question = _search_query(state)
    started = time.monotonic()
    ranked = rerank(question, state["retrieved_chunks"])
    elapsed = int((time.monotonic() - started) * 1000)
    logger.info("rerank: %d chunks sélectionnés en %d ms", len(ranked), elapsed)
    metadata = dict(state.get("_metadata") or {})
    metadata["rerank_ms"] = metadata.get("rerank_ms", 0) + elapsed
    return {"reranked_chunks": ranked, "_metadata": metadata}


def node_await_source_selection(state: AgentState) -> dict[str, Any]:
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


def node_reconstruct_context(state: AgentState) -> dict[str, Any]:
    """Reconstruit le contexte enrichi pour chaque élément sélectionné.

    Première passe : éléments choisis par l'utilisateur. Itérations suivantes
    (recherche déclenchée par le LLM) : top-3 des nouveaux chunks reranqués,
    ajoutés aux contextes déjà reconstruits — sans repasser par la sélection.
    """
    is_iteration = state.get("search_count", 0) > 1
    top_k = state.get("max_sources") or settings.auto_select_top_k

    if is_iteration:
        element_ids = [c.element_id for c in state["reranked_chunks"][:top_k]]
        contexts: list[SectionContext] = list(state.get("enriched_contexts") or [])
    else:
        element_ids = state.get("selected_element_ids") or []
        if not element_ids:
            # Personne n'a choisi : /answer fonctionne ainsi par construction,
            # et le flux interactif y tombe si la sélection revient vide.
            element_ids = [c.element_id for c in state["reranked_chunks"][:top_k]]
            logger.info("Aucune source sélectionnée, reprise des %d mieux classées.", top_k)
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


async def node_generate(state: AgentState) -> dict[str, Any]:
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

    started = time.monotonic()
    parts: list[str] = []
    # Rempli par le callback si le modèle émet un appel d'outil natif.
    tool_queries: list[str] = []

    async for token in generate_stream(
        question=state["question"],
        contexts=state["enriched_contexts"],
        chat_history=state.get("chat_history"),
        on_tool_call=tool_queries.append,
    ):
        parts.append(token)
        if writer:
            writer({"token": token})

    response = "".join(parts)
    logger.info("generate: réponse de %d caractères", len(response))

    # Le modèle peut demander une recherche supplémentaire de deux façons.
    # L'appel d'outil natif fait foi : il est structuré, donc sans ambiguïté.
    next_query: str | None = tool_queries[0] if tool_queries else None
    origine = "outil natif"

    if next_query is None:
        # Repli pour les modèles sans tool-calling : repérer l'appel dans la
        # prose. Fragile — le modèle doit produire la syntaxe exacte, et les
        # tokens sont déjà partis à l'écran — mais c'est le seul signal
        # disponible dans ce cas.
        match = re.search(r"search_vectors\([\"'](.+?)[\"']\)", response)
        if match:
            next_query = match.group(1)
            origine = "prose (repli)"

    needs_more = bool(next_query) and (
        state.get("search_count", 0) < settings.max_search_iterations
    )
    if needs_more:
        logger.info("Recherche supplémentaire demandée [%s] : %r", origine, next_query)
    elif next_query:
        logger.info("Recherche supplémentaire ignorée : plafond d'itérations atteint.")
        next_query = None

    # La syntaxe d'appel d'outil ne doit jamais apparaître dans la réponse finale
    response = re.sub(r"search_vectors\([\"'].+?[\"']\)", "", response).strip()

    metadata = dict(state.get("_metadata") or {})
    metadata["generation_ms"] = metadata.get("generation_ms", 0) + int(
        (time.monotonic() - started) * 1000
    )

    return {
        "response": response,
        "needs_more_info": needs_more,
        "next_query": next_query,
        "_metadata": metadata,
    }


def resolve_citations(
    response: str,
    contexts: list[SectionContext],
    chunks: list[ChunkResult],
) -> tuple[list[Citation], list[ImageRef]]:
    """Résout les marqueurs `[src:ID]` et `[img:ID]` d'une réponse.

    Rien ici ne dépend du graphe LangGraph : la fonction est appelée par le
    nœud de post-traitement comme par l'endpoint de génération directe, qui
    rendait auparavant `citations: []` en dur.

    Un identifiant que ni les contextes ni les chunks ne connaissent est
    ignoré : le modèle l'a inventé, et le résoudre serait mentir.

    Args:
        response: Le texte généré, marqueurs compris.
        contexts: Sections reconstruites soumises au LLM.
        chunks: Chunks reranqués — seuls porteurs de l'ouvrage.

    Returns:
        (citations, images), chacune sans doublon et dans l'ordre du texte.
    """
    chunks_map: dict[str, ChunkResult] = {c.element_id: c for c in chunks}

    # Les [src:ID] et [img:ID] référencent surtout des éléments des sections
    # reconstruites, qui ne figurent pas dans les chunks reranqués : on indexe
    # les deux. Le nom du document est porté par SectionContext ; l'ouvrage,
    # lui, n'existe que dans les métadonnées vectorielles.
    # L'ouvrage vient du graphe quand il y est, des chunks sinon : la
    # génération directe n'a pas de chunks, et une citation sans ouvrage ne dit
    # pas de quel livre elle vient.
    collections = {c.filename: c.collection for c in chunks if c.collection}

    media_map: dict[str, str] = {}
    elements_map: dict[str, Citation] = {}
    for ctx in contexts:
        # Les éléments des sections voisines sont citables au même titre que
        # ceux de la section trouvée : ils sont dans le prompt.
        for elem in (*ctx.before, *ctx.elements, *ctx.after):
            if elem.minio_url:
                media_map.setdefault(elem.node_id, elem.minio_url)
            elements_map.setdefault(
                elem.node_id,
                Citation(
                    element_id=elem.node_id,
                    filename=ctx.filename,
                    collection=ctx.collection or collections.get(ctx.filename, ""),
                    section_title=ctx.section_title,
                    page_no=elem.page_no,
                    text_excerpt=(elem.text or "")[:150],
                ),
            )
    for reranked in chunks:
        if reranked.minio_url:
            media_map.setdefault(reranked.element_id, reranked.minio_url)

    # Citations résolues d'abord depuis les chunks (document et page fiables),
    # sinon depuis les éléments des sections reconstruites.
    citations: list[Citation] = []
    cited: set[str] = set()
    for match in re.finditer(r"\[src:([a-f0-9]+)\]", response):
        eid = match.group(1)
        if eid in cited:
            continue
        chunk = chunks_map.get(eid)
        if chunk is not None:
            citations.append(
                Citation(
                    element_id=eid,
                    filename=chunk.filename,
                    collection=chunk.collection,
                    section_title=chunk.section_title,
                    page_no=chunk.page_no,
                    text_excerpt=chunk.document[:150],
                )
            )
            cited.add(eid)
        elif eid in elements_map:
            citations.append(elements_map[eid])
            cited.add(eid)

    # Images servies via le proxy /media : les URLs internes minio:9000 ne sont
    # pas résolvables depuis le navigateur.
    images: list[ImageRef] = []
    for match in re.finditer(r"\[img:([a-f0-9]+)\]", response):
        eid = match.group(1)
        minio_url = media_map.get(eid)
        if minio_url and not any(i.element_id == eid for i in images):
            images.append(ImageRef(element_id=eid, minio_url=to_media_path(minio_url)))

    return citations, images


def node_postprocess(state: AgentState) -> dict[str, Any]:
    """Extrait les citations [src:ID] et les références images [img:ID]."""
    citations, images = resolve_citations(
        state.get("response", ""),
        state.get("enriched_contexts", []),
        state.get("reranked_chunks", []),
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

    graph.add_node("rewrite", node_rewrite)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("rerank", node_rerank)
    graph.add_node("await_source_selection", node_await_source_selection)
    graph.add_node("reconstruct_context", node_reconstruct_context)
    graph.add_node("generate", node_generate)
    graph.add_node("postprocess", node_postprocess)

    graph.add_edge("rewrite", "retrieve")
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

    graph.set_entry_point("rewrite")
    return graph


# Gestionnaires de contexte des checkpointers ouverts, refermés à l'arrêt.
_ouverts: list[Any] = []


async def build_checkpointer() -> BaseCheckpointSaver[Any]:
    """Ouvre le checkpointer qui persiste les sessions entre /chat/start et /resume.

    **Asynchrone obligatoirement.** Le flux interactif passe par `ainvoke`,
    `astream`, `aget_state` et `aupdate_state` ; le `SqliteSaver` synchrone lève
    alors `NotImplementedError: does not support async methods` et toute la
    session échoue en 500. Seul `AsyncSqliteSaver` convient.

    Sur disque par défaut : en mémoire, une session en attente de sélection ne
    survit pas au redémarrage de l'API, et deux workers uvicorn ne partagent pas
    leurs threads — /chat/resume tomberait sur un process n'ayant jamais vu le
    thread_id.

    Repli en mémoire si le fichier est inaccessible (volume non monté, disque en
    lecture seule) : mieux vaut un service dégradé qu'un service mort.
    """
    path = settings.checkpoint_db_path
    if not path:
        logger.info("Checkpointer en mémoire (CHECKPOINT_DB_PATH vide).")
        return MemorySaver()
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # `from_conn_string` est le constructeur supporté : il ouvre la
        # connexion comme la bibliothèque l'attend. La construire à la main
        # depuis `aiosqlite.connect` produisait un objet sans `is_alive`, que
        # `setup()` exige — les versions récentes d'aiosqlite n'héritent plus
        # de Thread.
        gestionnaire = AsyncSqliteSaver.from_conn_string(path)
        saver = await gestionnaire.__aenter__()
        await saver.setup()
        _ouverts.append(gestionnaire)
        logger.info("Checkpointer SQLite asynchrone : %s", path)
        return saver
    except Exception:
        logger.exception("Checkpointer SQLite indisponible (%s), repli en mémoire.", path)
        return MemorySaver()


async def close_checkpointers() -> None:
    """Referme les checkpointers ouverts par `build_checkpointer`."""
    while _ouverts:
        gestionnaire = _ouverts.pop()
        try:
            await gestionnaire.__aexit__(None, None, None)
        except Exception:
            logger.debug("Fermeture du checkpointer impossible", exc_info=True)


def compile_interactive(checkpointer: BaseCheckpointSaver[Any]) -> Any:
    """Compile le graphe interactif : interruption avant la sélection des sources."""
    return build_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=["await_source_selection"],
    )

# Même graphe, sans interruption ni checkpointer : la sélection des sources est
# automatique. C'est ce que consomme POST /answer, et donc ce sur quoi porte
# toute campagne d'évaluation — le flux interactif n'est pas rejouable en batch.
answer_graph = build_graph().compile()
