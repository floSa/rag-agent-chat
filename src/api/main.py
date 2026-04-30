import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import agent_graph
from src.agent.graph_context import reconstruct_section
from src.agent.llm import generate_stream
from src.agent.retriever import group_by_document, rerank, retrieve
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

# Stockage en mémoire des états LangGraph en cours (thread_id → state)
# En production, utiliser une base de données ou Redis
_graph_states: dict[str, dict] = {}


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", ollama_model=settings.ollama_model)


# ─── Retrieval ────────────────────────────────────────────────────────────────

@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """Retrieval brut ChromaDB sans reranking."""
    chunks = retrieve(req.question, top_k=req.top_k)
    return SearchResponse(question=req.question, chunks=chunks)


# ─── Reranking + groupement ───────────────────────────────────────────────────

@app.post("/sources", response_model=SourcesResponse)
async def sources(req: SearchRequest) -> SourcesResponse:
    """Retrieval + reranking + groupement par document."""
    chunks = retrieve(req.question)
    ranked = rerank(req.question, chunks)
    groups = group_by_document(ranked)
    return SourcesResponse(question=req.question, groups=groups)


# ─── Graph context ────────────────────────────────────────────────────────────

@app.get("/context/{element_id}")
async def context(element_id: str) -> dict:
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
            ctx = reconstruct_section(eid)
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
        "chat_history": [],
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

    # Exécuter jusqu'à l'interruption (avant await_source_selection)
    result = await agent_graph.ainvoke(initial_state, config)
    _graph_states[thread_id] = result

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
    thread_id = req.thread_id
    if thread_id not in _graph_states:
        raise HTTPException(
            status_code=404,
            detail="Session introuvable. Relancez /chat/start.",
        )

    config = {"configurable": {"thread_id": thread_id}}
    state = _graph_states[thread_id]
    state["selected_element_ids"] = req.selected_element_ids

    result = await agent_graph.ainvoke(state, config)
    _graph_states.pop(thread_id, None)

    return ChatResponse(
        answer=result.get("response", ""),
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count", 1),
    )
