import json
import logging
import uuid
from collections.abc import AsyncIterator

import httpx
from anyio import to_thread
from fastapi import FastAPI, HTTPException, Path, Response
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import agent_graph
from src.agent.graph_context import ping as nebula_ping
from src.agent.graph_context import reconstruct_section
from src.agent.llm import generate_stream
from src.agent.minio_client import get_object_bytes
from src.agent.retriever import group_by_document, rerank, retrieve
from src.agent.retriever import ping as chroma_ping
from src.agent.settings import settings
from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SearchRequest,
    SearchResponse,
    SourceSelectionRequest,
    SourcesResponse,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="rag-agent-chat",
    description="API de l'agent RAG conversationnel",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            services["ollama"] = resp.status_code == 200
    except httpx.HTTPError:
        services["ollama"] = False

    status = "ok" if all(services.values()) else "degraded"
    return HealthResponse(status=status, ollama_model=settings.ollama_model, services=services)


# ─── Retrieval ────────────────────────────────────────────────────────────────

# Endpoints `def` (et non `async def`) : l'inférence des modèles (embedding,
# cross-encoder) et les requêtes Nebula sont synchrones et CPU-bound — FastAPI
# les exécute dans son threadpool, sans bloquer l'event loop.

@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    """Retrieval brut ChromaDB sans reranking."""
    chunks = retrieve(req.question, top_k=req.top_k)
    return SearchResponse(question=req.question, chunks=chunks)


# ─── Reranking + groupement ───────────────────────────────────────────────────

@app.post("/sources", response_model=SourcesResponse)
def sources(req: SearchRequest) -> SourcesResponse:
    """Retrieval + reranking + groupement par document."""
    chunks = retrieve(req.question)
    ranked = rerank(req.question, chunks)
    groups = group_by_document(ranked)
    return SourcesResponse(question=req.question, groups=groups)


# ─── Graph context ────────────────────────────────────────────────────────────

@app.get("/context/{element_id}")
def context(element_id: str = Path(pattern=r"^[a-f0-9]{10}$")) -> dict:
    """Reconstruit le contexte enrichi pour un element_id donné."""
    try:
        ctx = reconstruct_section(element_id)
        return ctx.model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── Chat (génération directe, sans LangGraph) ────────────────────────────────

@app.post("/chat/simple")
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

    if req.stream:
        async def stream_generator() -> AsyncIterator[dict]:
            async for token in generate_stream(req.question, contexts, req.chat_history):
                yield {"data": json.dumps({"token": token})}
            yield {"data": json.dumps({"done": True})}

        return EventSourceResponse(stream_generator())

    from src.agent.llm import generate

    response = await generate(req.question, contexts, req.chat_history)
    return ChatResponse(answer=response, citations=[], images=[], search_count=1)


# ─── Chat avec agentic loop (LangGraph) ───────────────────────────────────────

@app.post("/chat/start")
async def chat_start(req: SearchRequest) -> dict:
    """Démarre le flux LangGraph : retrieval + reranking, puis suspend en attente
    de la sélection des sources.

    Retourne un thread_id à passer à /chat/resume.
    """
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "question": req.question,
        # Multi-turn : derniers échanges seulement, pour borner le contexte
        "chat_history": req.chat_history[-6:],
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "selected_element_ids": [],
        "enriched_contexts": [],
        "response": "",
        "citations": [],
        "images": [],
        "search_count": 0,
        "needs_more_info": False,
        "next_query": None,
        "_metadata": {},
    }

    # Exécuter jusqu'à l'interruption (avant await_source_selection) ;
    # l'état est persisté par le checkpointer LangGraph sous ce thread_id.
    result = await agent_graph.ainvoke(initial_state, config)

    groups = group_by_document(result.get("reranked_chunks", []))
    return {
        "thread_id": thread_id,
        "question": req.question,
        "groups": [g.model_dump() for g in groups],
    }


@app.post("/chat/resume")
async def chat_resume(req: SourceSelectionRequest) -> EventSourceResponse | ChatResponse:
    """Reprend le flux LangGraph après sélection des sources par l'utilisateur.

    Reconstruit le contexte, génère la réponse, post-traite les citations.
    """
    config = {"configurable": {"thread_id": req.thread_id}}

    snapshot = await agent_graph.aget_state(config)
    if not snapshot.values or not snapshot.next:
        raise HTTPException(
            status_code=404,
            detail="Session introuvable ou déjà terminée. Relancez /chat/start.",
        )

    # Injecter la sélection dans l'état persisté, puis reprendre là où le
    # graphe s'était interrompu (input None = resume, pas un nouveau run).
    await agent_graph.aupdate_state(
        config, {"selected_element_ids": req.selected_element_ids}
    )

    if req.stream:
        async def stream_generator() -> AsyncIterator[dict]:
            final_state: dict = {}
            # "custom" : tokens émis par node_generate ; "values" : état complet
            # après chaque nœud (le dernier reçu = état final).
            async for mode, chunk in agent_graph.astream(
                None, config, stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    yield {"data": json.dumps(chunk)}
                elif mode == "values":
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

        return EventSourceResponse(stream_generator())

    result = await agent_graph.ainvoke(None, config)
    return ChatResponse(
        answer=result.get("response", ""),
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count", 1),
    )


# ─── Médias (proxy MinIO) ─────────────────────────────────────────────────────

@app.get("/media/{object_name:path}")
def media(object_name: str) -> Response:
    """Sert un objet MinIO (image croppée) au navigateur.

    L'endpoint interne minio:9000 n'est pas résolvable hors du réseau Docker :
    l'API joue le rôle de proxy pour les images référencées dans les réponses.
    """
    data = get_object_bytes(object_name)
    if data is None:
        raise HTTPException(status_code=404, detail="Objet introuvable.")
    return Response(content=data, media_type="image/png")
