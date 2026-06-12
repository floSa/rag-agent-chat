import logging
from functools import lru_cache

import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer

from src.agent.settings import settings
from src.api.schemas import ChunkResult, SourceGroup

logger = logging.getLogger(__name__)


# ─── Singletons chargés une seule fois au démarrage ──────────────────────────

@lru_cache(maxsize=1)
def _get_embedding_model() -> SentenceTransformer:
    logger.info("Chargement du modèle d'embedding : %s", settings.embedding_model_name)
    return SentenceTransformer(settings.embedding_model_name)


@lru_cache(maxsize=1)
def _get_rerank_model() -> CrossEncoder:
    logger.info("Chargement du modèle de reranking : %s", settings.rerank_model)
    return CrossEncoder(settings.rerank_model)


@lru_cache(maxsize=1)
def _get_chroma_collection() -> chromadb.Collection:
    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    collection = client.get_collection(settings.chroma_collection)
    logger.info(
        "ChromaDB connecté : %s:%s / collection '%s'",
        settings.chroma_host,
        settings.chroma_port,
        settings.chroma_collection,
    )
    return collection


def ping() -> bool:
    """Vérifie que ChromaDB répond (utilisé par /health)."""
    try:
        _get_chroma_collection().count()
        return True
    except Exception:
        return False


# ─── Retrieval ────────────────────────────────────────────────────────────────

def retrieve(question: str, top_k: int | None = None) -> list[ChunkResult]:
    """Encode la question et interroge ChromaDB, retourne top_k chunks bruts."""
    k = top_k or settings.retrieval_top_k
    embedding_model = _get_embedding_model()
    collection = _get_chroma_collection()

    query_embedding: list[float] = embedding_model.encode(question).tolist()  # type: ignore[union-attr]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[ChunkResult] = []
    docs = results.get("documents") or [[]]
    metas = results.get("metadatas") or [[]]
    dists = results.get("distances") or [[]]
    ids = results.get("ids") or [[]]

    for chunk_id, doc, meta, dist in zip(ids[0], docs[0], metas[0], dists[0], strict=False):
        chunks.append(
            ChunkResult(
                chunk_id=chunk_id,
                element_id=meta.get("element_id", ""),
                graph_node_id=meta.get("graph_node_id", ""),
                document=doc,
                filename=meta.get("filename", ""),
                page_no=int(meta.get("page_no", 0)),
                label=meta.get("label", ""),
                minio_url=meta.get("minio_url") or None,
                page_position=int(meta.get("page_position", 0)),
                ref_position=int(meta.get("ref_position", 0)),
                distance=float(dist),
            )
        )

    logger.info("Retrieval : %d chunks récupérés pour '%s'", len(chunks), question[:60])
    return chunks


# ─── Reranking ────────────────────────────────────────────────────────────────

def rerank(question: str, chunks: list[ChunkResult]) -> list[ChunkResult]:
    """Applique le cross-encoder et retourne les top RERANK_TOP_K chunks."""
    if not chunks:
        return []

    rerank_model = _get_rerank_model()
    pairs = [[question, c.document] for c in chunks]
    scores: list[float] = rerank_model.predict(pairs).tolist()  # type: ignore[union-attr]

    ranked = sorted(
        [(chunk, score) for chunk, score in zip(chunks, scores, strict=False)],
        key=lambda x: x[1],
        reverse=True,
    )

    top = ranked[: settings.rerank_top_k]
    result = []
    for chunk, score in top:
        chunk.rerank_score = score
        result.append(chunk)

    logger.info("Reranking : %d chunks sélectionnés (top-%d)", len(result), settings.rerank_top_k)
    return result


# ─── Groupement par document ──────────────────────────────────────────────────

def group_by_document(chunks: list[ChunkResult]) -> list[SourceGroup]:
    """Regroupe les chunks par document source, triés par meilleur score."""
    groups: dict[str, list[ChunkResult]] = {}
    for chunk in chunks:
        groups.setdefault(chunk.filename, []).append(chunk)

    result = []
    for filename, doc_chunks in groups.items():
        best = max(
            (c.rerank_score for c in doc_chunks if c.rerank_score is not None),
            default=0.0,
        )
        result.append(
            SourceGroup(
                filename=filename,
                best_score=best,
                chunks=sorted(doc_chunks, key=lambda c: c.rerank_score or 0.0, reverse=True),
            )
        )

    return sorted(result, key=lambda g: g.best_score, reverse=True)
