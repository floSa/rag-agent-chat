import json
import logging
import secrets
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from anyio import to_thread
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Response
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import (
    answer_graph,
    build_checkpointer,
    close_checkpointers,
    compile_interactive,
    resolve_citations,
)
from src.agent.graph_context import ping as nebula_ping
from src.agent.graph_context import reconstruct_section
from src.agent.llm import generate_stream
from src.agent.minio_client import get_object_bytes
from src.agent.retriever import group_by_document, lexical_ready, rerank, retrieve
from src.agent.retriever import ping as chroma_ping
from src.agent.settings import settings
from src.agent.state import AgentState
from src.agent.usage import initialiser as usage_initialiser
from src.agent.usage import record_completion, record_feedback, record_start
from src.agent.usage import stats as usage_stats
from src.api.schemas import (
    MAX_HISTORY_MESSAGES,
    AnswerRequest,
    AnswerResponse,
    ChatRequest,
    ChatResponse,
    Citation,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    ImageRef,
    RetrievedContext,
    SearchRequest,
    SearchResponse,
    SectionContext,
    SourceSelectionRequest,
    SourcesResponse,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Graphe interactif, compilé au démarrage : son checkpointer ouvre une
# connexion asynchrone, ce qui ne peut pas se faire à l'import du module.
_interactive: Any = None


def interactive_graph() -> Any:
    """Graphe du flux interactif, une fois le service démarré."""
    if _interactive is None:
        raise HTTPException(status_code=503, detail="Service en cours de démarrage.")
    return _interactive


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ouvre le checkpointer avant de servir, le referme à l'arrêt."""
    global _interactive
    checkpointer = await build_checkpointer()
    _interactive = compile_interactive(checkpointer)
    # Avant de servir : c'est le seul moment où fixer le mode de journalisation
    # de la base de capture est sûr. Le faire dans le chemin d'écriture faisait
    # perdre des interactions simultanées (cf. usage.initialiser).
    await usage_initialiser()
    # La taille de l'actif au démarrage. Aucune purge n'existe et c'est
    # délibéré : la contrepartie est qu'elle doit être VISIBLE, sans quoi un jeu
    # de données qui grossit sans qu'on le sache redevient une fuite.
    capture = await usage_stats()
    logger.info(
        "Capture d'usage %s : %d interactions, %d sources, %d ko (%s)",
        "active" if capture.enabled else "désactivée",
        capture.interactions,
        capture.sources,
        capture.size_bytes // 1024,
        capture.path,
    )
    try:
        yield
    finally:
        await close_checkpointers()


app = FastAPI(
    title="rag-agent-chat",
    description="API de l'agent RAG conversationnel",
    version="0.1.0",
    lifespan=lifespan,
)

# Origines explicites plutôt que « * » : sans cela, n'importe quelle page web
# ouverte dans le navigateur de l'utilisateur peut interroger l'API — et, tant
# qu'aucune clé n'est exigée, lire le corpus.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Exige la clé si `API_KEY` est renseignée.

    Vide — le cas d'un déploiement local derrière un pare-feu — la dépendance
    ne fait rien. Renseignée, toute route sauf `/health` l'exige : une sonde
    doit rester interrogeable sans secret.
    """
    if not settings.api_key:
        return
    if not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Clé d'API absente ou invalide.")

# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Vérifie réellement les trois dépendances (Chroma, Nebula, Ollama).

    Retourne toujours 200 (pour ne pas déclencher de restart en boucle) avec
    le détail par service ; status passe à "degraded" si l'une est down.
    """
    services: dict[str, bool] = {
        "chromadb": await to_thread.run_sync(chroma_ping),
        "nebulagraph": await to_thread.run_sync(nebula_ping),
        # L'index BM25 se construit au premier appel : tant qu'il est faux, la
        # recherche fonctionne en dense seul et la première requête paiera
        # sa construction.
        "index_lexical": await to_thread.run_sync(lexical_ready),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            services["ollama"] = resp.status_code == 200
    except httpx.HTTPError:
        services["ollama"] = False

    # L'index lexical n'est pas une dépendance : son absence dégrade la
    # recherche, elle ne l'empêche pas. Le healthcheck Docker ne doit pas
    # redémarrer le service pour ça.
    essentiels = {k: v for k, v in services.items() if k != "index_lexical"}
    status = "ok" if all(essentiels.values()) else "degraded"
    # `stats` absorbe ses propres échecs et rend des zéros : une sonde qui
    # tombe parce qu'une base d'observation est illisible serait une régression,
    # pas une mesure. Le compteur `failures` dit alors ce qui s'est passé.
    return HealthResponse(
        status=status,
        ollama_model=settings.ollama_model,
        services=services,
        usage=await usage_stats(),
    )


# ─── Retrieval ────────────────────────────────────────────────────────────────

# Endpoints `def` (et non `async def`) : l'inférence des modèles (embedding,
# cross-encoder) et les requêtes Nebula sont synchrones et CPU-bound — FastAPI
# les exécute dans son threadpool, sans bloquer l'event loop.

@app.post("/search", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
def search(req: SearchRequest) -> SearchResponse:
    """Retrieval brut ChromaDB sans reranking."""
    chunks = retrieve(req.question, top_k=req.top_k)
    return SearchResponse(question=req.question, chunks=chunks)


# ─── Reranking + groupement ───────────────────────────────────────────────────

@app.post("/sources", response_model=SourcesResponse, dependencies=[Depends(require_api_key)])
def sources(req: SearchRequest) -> SourcesResponse:
    """Retrieval + reranking + groupement par document."""
    chunks = retrieve(req.question)
    ranked = rerank(req.question, chunks)
    groups = group_by_document(ranked)
    return SourcesResponse(question=req.question, groups=groups)


# ─── Graph context ────────────────────────────────────────────────────────────

@app.get("/context/{element_id}", dependencies=[Depends(require_api_key)])
def context(element_id: str = Path(pattern=r"^[a-f0-9]{10}$")) -> dict[str, Any]:
    """Reconstruit le contexte enrichi pour un element_id donné."""
    try:
        ctx = reconstruct_section(element_id)
        return ctx.model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── Chat (génération directe, sans LangGraph) ────────────────────────────────

async def _capturer_generation_directe(
    thread_id: str,
    question: str,
    reponse: str,
    citations: list[Citation],
    images: list[ImageRef],
    contexts: list[SectionContext],
) -> None:
    """Enregistre une génération directe : la question et ce qu'elle a produit.

    Les deux écritures ont lieu à la fin, jamais avant la réponse : cet endpoint
    diffuse, et rien de synchrone n'entre dans le chemin de diffusion.
    """
    await record_start(thread_id=thread_id, endpoint="chat_simple", question=question)
    await record_completion(
        thread_id=thread_id,
        response=reponse,
        citations=citations,
        images=images,
        search_count=1,
        submitted=contexts,
    )


@app.post("/chat/simple", response_model=None, dependencies=[Depends(require_api_key)])
async def chat_simple(req: ChatRequest) -> EventSourceResponse | ChatResponse:
    """Génération directe (sans agentic loop) à partir des sources sélectionnées.

    Utilise les element_ids sélectionnés pour reconstruire le contexte, puis
    appelle le LLM. Supporte le streaming SSE.
    """
    if not req.selected_element_ids:
        raise HTTPException(
            status_code=400,
            detail="Sélectionnez au moins une source avant de générer.",
        )

    contexts = []
    for eid in req.selected_element_ids:
        try:
            # Reconstruction synchrone (requêtes Nebula) → threadpool
            ctx = await to_thread.run_sync(reconstruct_section, eid)
            contexts.append(ctx)
        except Exception:
            logger.exception("Erreur reconstruction pour %s", eid)

    if not contexts:
        raise HTTPException(
            status_code=500,
            detail="Impossible de reconstruire le contexte des sources sélectionnées.",
        )

    # La capture de cet endpoint n'écrit AUCUNE source proposée : le client
    # arrive avec ses element_ids déjà choisis, rien ne lui a été soumis. Y
    # inscrire ses sources comme « retenues » gonflerait le taux de retenue
    # d'une décision que personne n'a prise. La question, elle, compte : c'est
    # la distribution des classes de questions qu'on cherche à connaître.
    thread_id = str(uuid.uuid4())

    if req.stream:
        async def stream_generator() -> AsyncIterator[dict[str, Any]]:
            morceaux: list[str] = []
            async for token in generate_stream(
                req.question, contexts, req.chat_history[-MAX_HISTORY_MESSAGES:]
            ):
                morceaux.append(token)
                yield {"data": json.dumps({"token": token})}
            reponse = "".join(morceaux)
            citations, images = resolve_citations(reponse, contexts, [])
            yield {
                "data": json.dumps(
                    {
                        "done": True,
                        "answer": reponse,
                        # Rendu au client pour qu'il puisse noter la réponse :
                        # c'est le seul endroit où il apprend ce thread_id.
                        "thread_id": thread_id,
                        "citations": [c.model_dump() for c in citations],
                        "images": [i.model_dump() for i in images],
                    }
                )
            }
            await _capturer_generation_directe(
                thread_id, req.question, reponse, citations, images, contexts
            )

        return EventSourceResponse(stream_generator())

    from src.agent.llm import generate

    # Cet endpoint rendait `citations: []` en dur : il generait des reponses
    # truffees de marqueurs [src:...] que personne ne resolvait, dans un projet
    # dont c'est precisement l'objet.
    # Même profondeur d'historique que /chat/start et /answer : cet endpoint
    # soumettait tout ce que le client envoyait, donc un autre prompt pour la
    # même conversation selon la route empruntée.
    response = await generate(req.question, contexts, req.chat_history[-MAX_HISTORY_MESSAGES:])
    citations, images = resolve_citations(response, contexts, [])
    await _capturer_generation_directe(
        thread_id, req.question, response, citations, images, contexts
    )
    return ChatResponse(
        answer=response,
        citations=citations,
        images=images,
        search_count=1,
        thread_id=thread_id,
    )


# ─── Réponse directe, sans sélection humaine ──────────────────────────────────

@app.post("/answer", response_model=AnswerResponse, dependencies=[Depends(require_api_key)])
async def answer(req: AnswerRequest) -> AnswerResponse:
    """Question → réponse, sans interruption ni sélection des sources.

    Le flux interactif (/chat/start + sélection + /chat/resume) n'est pas
    rejouable en batch : il attend un humain. Cet endpoint exécute le même
    graphe avec les sources les mieux classées, et retourne en plus les
    passages réellement soumis au LLM et le temps passé à chaque étage.

    Sans les contextes, une campagne d'évaluation ne peut pas distinguer un
    échec de recherche d'un échec de génération — c'est la mesure qui permet
    d'attribuer la faute.
    """
    initial_state: AgentState = {
        "question": req.question,
        "chat_history": req.chat_history[-MAX_HISTORY_MESSAGES:],
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "search_query": None,
        "search_translation": None,
        "selected_element_ids": [],
        "max_sources": req.max_sources,
        "top_k": req.top_k,
        "enriched_contexts": [],
        "response": "",
        "citations": [],
        "images": [],
        "search_count": 0,
        "needs_more_info": False,
        "next_query": None,
        "dropped_contexts": 0,
        "_metadata": {},
    }

    # Un seul passage dans le graphe : la version précédente exécutait
    # retrieval et reranking ici PUIS relançait le graphe depuis son point
    # d'entrée, qui les refaisait. Les nœuds se chronomètrent eux-mêmes.
    limite: RunnableConfig = {"recursion_limit": 50}
    result = await answer_graph.ainvoke(initial_state, limite)
    timings = result.get("_metadata") or {}
    ranked = result.get("reranked_chunks", [])

    enriched = result.get("enriched_contexts", [])
    # Le chiffre que node_generate a réellement appliqué, remonté par l'état.
    # Le recalculer ici journalisait chaque troncature deux fois et rendait le
    # gabarit une fois de plus par candidate — et deux calculs séparés dérivent,
    # ce que ce champ sert précisément à publier.
    dropped = result.get("dropped_contexts", 0)
    by_element = {c.element_id: c for c in ranked}

    contexts = [
        RetrievedContext(
            element_id=ctx.element_id,
            section_id=ctx.section_id,
            filename=ctx.filename,
            collection=getattr(by_element.get(ctx.element_id), "collection", ""),
            source_path=getattr(by_element.get(ctx.element_id), "source_path", ""),
            section_title=ctx.section_title,
            language=getattr(by_element.get(ctx.element_id), "language", ""),
            page_no=getattr(by_element.get(ctx.element_id), "page_no", 0),
            relevance=getattr(by_element.get(ctx.element_id), "relevance", None),
            text=ctx.markdown,
        )
        for ctx in enriched
    ]

    # Capturé comme le flux interactif, mais sous `endpoint='answer'` : la
    # sélection est automatique ici, aucune décision humaine n'y figure. C'est
    # ce qui permet de comparer une campagne à l'usage réel — à condition de
    # filtrer, une campagne écrivant 138 interactions d'un coup.
    thread_id = str(uuid.uuid4())
    await record_start(
        thread_id=thread_id,
        endpoint="answer",
        question=req.question,
        search_query=result.get("search_query"),
        search_translation=result.get("search_translation"),
        ranking=ranked,
        timings=timings,
    )
    await record_completion(
        thread_id=thread_id,
        response=result.get("response", ""),
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count"),
        submitted=enriched,
        selected_element_ids=[c.element_id for c in enriched],
        # Seul endroit où le nombre de sources écartées est connu sans passer
        # par l'état du graphe : il vient d'être calculé juste au-dessus.
        dropped_contexts=dropped,
        timings=timings,
    )

    return AnswerResponse(
        question=req.question,
        answer=result.get("response", ""),
        retrieved_element_ids=[c.element_id for c in ranked],
        contexts=contexts,
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count", 1),
        retrieval_ms=timings.get("retrieval_ms", 0) + timings.get("rerank_ms", 0),
        generation_ms=timings.get("generation_ms", 0),
        dropped_contexts=dropped,
    )


# ─── Chat avec agentic loop (LangGraph) ───────────────────────────────────────

# Sessions LangGraph vivantes, de la plus ancienne à la plus récente. Le
# checkpointer en mémoire ne purge rien de lui-même : sans ce registre, chaque
# question laissait indéfiniment ses chunks, ses embeddings et ses contextes
# reconstruits en mémoire. Fuite lente mais certaine sur un service qui tourne.
_live_threads: OrderedDict[str, float] = OrderedDict()


def _register_thread(thread_id: str) -> None:
    """Enregistre une session et purge les périmées (âge ou nombre)."""
    now = time.monotonic()
    _live_threads[thread_id] = now

    expired = [
        tid
        for tid, started in _live_threads.items()
        if now - started > settings.session_ttl_seconds
    ]
    while len(_live_threads) - len(expired) > settings.max_live_sessions:
        oldest = next(iter(_live_threads))
        if oldest not in expired:
            expired.append(oldest)
        _live_threads.pop(oldest, None)

    for tid in expired:
        _live_threads.pop(tid, None)
        try:
            checkpointer = interactive_graph().checkpointer
            if isinstance(checkpointer, BaseCheckpointSaver):
                checkpointer.delete_thread(tid)
        except Exception:
            logger.debug("Purge du thread %s impossible", tid, exc_info=True)

    if expired:
        logger.info("Sessions purgées : %d (restantes : %d)", len(expired), len(_live_threads))


@app.post("/chat/start", dependencies=[Depends(require_api_key)])
async def chat_start(req: SearchRequest) -> dict[str, Any]:
    """Démarre le flux LangGraph : retrieval + reranking, puis suspend en attente
    de la sélection des sources.

    Retourne un thread_id à passer à /chat/resume.
    """
    thread_id = str(uuid.uuid4())
    _register_thread(thread_id)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "question": req.question,
        # Multi-turn : derniers échanges seulement, pour borner le contexte
        "chat_history": req.chat_history[-MAX_HISTORY_MESSAGES:],
        "search_query": None,
        "search_translation": None,
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "selected_element_ids": [],
        "max_sources": None,
        "top_k": req.top_k,
        "enriched_contexts": [],
        "response": "",
        "citations": [],
        "images": [],
        "search_count": 0,
        "needs_more_info": False,
        "next_query": None,
        "dropped_contexts": 0,
        "_metadata": {},
    }

    # Exécuter jusqu'à l'interruption (avant await_source_selection) ;
    # l'état est persisté par le checkpointer LangGraph sous ce thread_id.
    result = await interactive_graph().ainvoke(initial_state, config)

    groups = group_by_document(result.get("reranked_chunks", []))

    # Ouverture de l'enregistrement de capture. C'est ici, et nulle part
    # ailleurs, qu'on sait ce qui a été PROPOSÉ : /chat/resume ne verra que ce
    # qui a été retenu, et l'écart entre les deux est la donnée que ce lot
    # récolte. Les deux phases sont jointes par thread_id.
    await record_start(
        thread_id=thread_id,
        endpoint="chat",
        question=req.question,
        search_query=result.get("search_query"),
        search_translation=result.get("search_translation"),
        ranking=result.get("reranked_chunks", []),
        timings=result.get("_metadata") or {},
    )

    return {
        "thread_id": thread_id,
        "question": req.question,
        "groups": [g.model_dump() for g in groups],
    }


async def _completer_capture(
    thread_id: str, etat: dict[str, Any], selection: list[str]
) -> None:
    """Complète l'enregistrement d'usage avec ce que la génération a produit.

    `dropped_contexts` est lu dans l'état plutôt que recalculé : c'est le chiffre
    que `node_generate` a réellement appliqué au prompt, publié par le rappel
    `on_fit`. Le `.get` reste défensif — un état sans la clé enregistre NULL
    plutôt que 0, parce que 0 affirmerait qu'aucune source n'a été écartée — mais
    le graphe la porte désormais sur les trois chemins, et un test l'exerce sur
    des sections qui dépassent réellement la fenêtre.
    """
    await record_completion(
        thread_id=thread_id,
        response=etat.get("response", ""),
        citations=etat.get("citations", []),
        images=etat.get("images", []),
        search_count=etat.get("search_count"),
        submitted=etat.get("enriched_contexts", []),
        # La sélection HUMAINE, pas les sections soumises : deux éléments d'une
        # même section n'en produisent qu'une, et la boucle agentique peut en
        # ajouter que personne n'a jamais vues.
        selected_element_ids=selection,
        dropped_contexts=etat.get("dropped_contexts"),
        timings=etat.get("_metadata") or {},
    )


@app.post("/chat/resume", response_model=None, dependencies=[Depends(require_api_key)])
async def chat_resume(req: SourceSelectionRequest) -> EventSourceResponse | ChatResponse:
    """Reprend le flux LangGraph après sélection des sources par l'utilisateur.

    Reconstruit le contexte, génère la réponse, post-traite les citations.
    """
    config: RunnableConfig = {"configurable": {"thread_id": req.thread_id}}

    snapshot = await interactive_graph().aget_state(config)
    if not snapshot.values or not snapshot.next:
        raise HTTPException(
            status_code=404,
            detail="Session introuvable ou déjà terminée. Relancez /chat/start.",
        )

    # Injecter la sélection dans l'état persisté, puis reprendre là où le
    # graphe s'était interrompu (input None = resume, pas un nouveau run).
    await interactive_graph().aupdate_state(
        config, {"selected_element_ids": req.selected_element_ids}
    )

    if req.stream:
        async def stream_generator() -> AsyncIterator[dict[str, Any]]:
            final_state: dict[str, Any] = {}
            # "custom" : tokens émis par node_generate ; "values" : état complet
            # après chaque nœud (le dernier reçu = état final).
            async for mode, chunk in interactive_graph().astream(
                None, config, stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    yield {"data": json.dumps(chunk)}
                elif mode == "values" and isinstance(chunk, dict):
                    final_state = chunk
            yield {
                "data": json.dumps({
                    "done": True,
                    "answer": final_state.get("response", ""),
                    "citations": [c.model_dump() for c in final_state.get("citations", [])],
                    "images": [i.model_dump() for i in final_state.get("images", [])],
                    "search_count": final_state.get("search_count", 1),
                })
            }
            # APRÈS le dernier événement : la réponse est servie, l'écriture ne
            # coûte rien à qui attendait. Rien de synchrone n'entre dans le
            # chemin de diffusion, c'est la contrainte du lot.
            await _completer_capture(req.thread_id, final_state, req.selected_element_ids)

        return EventSourceResponse(stream_generator())

    result = await interactive_graph().ainvoke(None, config)
    await _completer_capture(req.thread_id, result, req.selected_element_ids)
    return ChatResponse(
        answer=result.get("response", ""),
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count", 1),
    )


# ─── Appréciation d'une réponse ───────────────────────────────────────────────

@app.post("/feedback", response_model=FeedbackResponse, dependencies=[Depends(require_api_key)])
async def feedback(req: FeedbackRequest) -> FeedbackResponse:
    """Attache une appréciation à une interaction déjà enregistrée.

    Note binaire : personne ne remplit une échelle, et un 3/5 ne se lit pas.
    Deux valeurs se comptent, et c'est ce qui rendra un jour un jeu doré réel
    utilisable — une question, ses sources validées, et un humain qui dit si la
    réponse valait quelque chose.

    Un `thread_id` inconnu rend 404 : c'est une erreur du client, il a inventé
    ou périmé son identifiant. Une capture désactivée ou en échec rend 200 avec
    `recorded: false` — ce n'est pas au client d'en porter la faute, et un 500
    ferait échouer une requête pour une observation perdue.
    """
    sort = await record_feedback(
        thread_id=req.thread_id, rating=req.rating, comment=req.comment
    )
    if sort == "inconnu":
        raise HTTPException(
            status_code=404,
            detail="Aucune interaction enregistrée sous ce thread_id.",
        )
    if sort == "desactive":
        return FeedbackResponse(recorded=False, detail="Capture d'usage désactivée.")
    if sort == "echec":
        return FeedbackResponse(
            recorded=False, detail="Enregistrement impossible, cf. journal du service."
        )
    return FeedbackResponse(recorded=True)


# ─── Médias (proxy MinIO) ─────────────────────────────────────────────────────

@app.get("/media/{object_name:path}", dependencies=[Depends(require_api_key)])
def media(object_name: str) -> Response:
    """Sert un objet MinIO (image croppée) au navigateur.

    L'endpoint interne minio:9000 n'est pas résolvable hors du réseau Docker :
    l'API joue le rôle de proxy pour les images référencées dans les réponses.
    """
    data = get_object_bytes(object_name)
    if data is None:
        raise HTTPException(status_code=404, detail="Objet introuvable.")
    return Response(content=data, media_type="image/png")
