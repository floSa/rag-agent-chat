import logging
import math
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


def reset_connection() -> None:
    """Oublie la collection mise en cache, pour la rouvrir au prochain appel."""
    _get_chroma_collection.cache_clear()


def ping() -> bool:
    """Vérifie que ChromaDB répond (utilisé par /health)."""
    try:
        _get_chroma_collection().count()
        return True
    except Exception:
        reset_connection()
        return False


# ─── Retrieval ────────────────────────────────────────────────────────────────

def retrieve(question: str, top_k: int | None = None) -> list[ChunkResult]:
    """Encode la question et interroge ChromaDB, retourne top_k chunks bruts."""
    k = top_k or settings.retrieval_top_k
    embedding_model = _get_embedding_model()
    collection = _get_chroma_collection()

    query_embedding: list[float] = embedding_model.encode(question).tolist()  # type: ignore[union-attr]

    def _query(coll: chromadb.Collection) -> dict:
        return coll.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

    try:
        results = _query(collection)
    except Exception:
        # La collection est mise en cache : si ChromaDB a redémarré, l'objet
        # pointe vers une connexion morte et toutes les recherches échouent
        # jusqu'au redémarrage de l'agent. On la rouvre et on retente une fois.
        logger.warning("ChromaDB injoignable, réouverture de la connexion et nouvel essai.")
        reset_connection()
        results = _query(_get_chroma_collection())

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
                collection=meta.get("collection") or "",
                source_path=meta.get("source_path") or "",
                section_title=meta.get("section_title") or "",
                language=meta.get("language") or "",
                depth=int(meta.get("depth") or 0),
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

def _sigmoid(x: float) -> float:
    """Ramène un logit de cross-encoder dans [0, 1].

    Monotone : l'ordre du classement est inchangé. Seule l'échelle devient
    interprétable — un seuil « 0.5 » veut enfin dire quelque chose.
    """
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    # Forme stable pour les logits très négatifs (exp(-x) déborde sinon).
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def dedupe_by_element(chunks: list[ChunkResult]) -> list[ChunkResult]:
    """Ne garde qu'un chunk par element_id, le mieux classé.

    Un bloc long est découpé par l'ingestion en fenêtres recouvrantes qui
    partagent leur ``element_id`` (``abc#0``, ``abc#1``, …). Comme elles se
    ressemblent, le reranker les remonte ensemble : elles consommaient
    plusieurs places du top-K pour un seul passage, et produisaient deux cases
    à cocher de même clé côté frontend.

    L'ordre d'entrée est préservé — la fonction est donc sûre après un tri.
    """
    best: dict[str, ChunkResult] = {}
    for chunk in chunks:
        current = best.get(chunk.element_id)
        if current is None:
            best[chunk.element_id] = chunk
            continue
        # À défaut de score de rerank, la distance vectorielle départage
        # (plus petite = plus proche).
        if chunk.rerank_score is not None and current.rerank_score is not None:
            if chunk.rerank_score > current.rerank_score:
                best[chunk.element_id] = chunk
        elif chunk.distance < current.distance:
            best[chunk.element_id] = chunk
    return list(best.values())


def rerank(question: str, chunks: list[ChunkResult]) -> list[ChunkResult]:
    """Applique le cross-encoder et retourne les top RERANK_TOP_K éléments.

    La déduplication a lieu **avant** la troncature au top-K : sinon plusieurs
    fenêtres d'un même passage occupent des places au détriment d'autres
    documents.
    """
    if not chunks:
        return []

    rerank_model = _get_rerank_model()
    pairs = [[question, c.document] for c in chunks]
    scores: list[float] = rerank_model.predict(pairs).tolist()  # type: ignore[union-attr]

    for chunk, score in zip(chunks, scores, strict=False):
        chunk.rerank_score = score
        chunk.relevance = _sigmoid(score)

    ranked = sorted(chunks, key=lambda c: c.rerank_score or 0.0, reverse=True)
    result = dedupe_by_element(ranked)[: settings.rerank_top_k]

    logger.info(
        "Reranking : %d chunks scorés → %d éléments distincts (top-%d)",
        len(chunks),
        len(result),
        settings.rerank_top_k,
    )
    return result


# ─── Groupement par document ──────────────────────────────────────────────────

def group_by_document(chunks: list[ChunkResult]) -> list[SourceGroup]:
    """Regroupe les chunks par document source, triés par meilleur score.

    Le groupement se fait sur ``source_path`` et non sur ``filename`` : deux
    ouvrages peuvent contenir un chapitre « Préface », et les fusionner rendait
    toute citation ambiguë. Repli sur ``filename`` si la métadonnée est absente
    (documents ingérés avant qu'elle n'existe).
    """
    groups: dict[str, list[ChunkResult]] = {}
    for chunk in dedupe_by_element(chunks):
        groups.setdefault(chunk.document_key, []).append(chunk)

    result = []
    for doc_chunks in groups.values():
        head = doc_chunks[0]
        best = max(
            (c.rerank_score for c in doc_chunks if c.rerank_score is not None),
            default=0.0,
        )
        best_relevance = max((c.relevance or 0.0 for c in doc_chunks), default=0.0)
        result.append(
            SourceGroup(
                filename=head.filename,
                collection=head.collection,
                source_path=head.source_path,
                best_score=best,
                best_relevance=best_relevance,
                chunks=sorted(doc_chunks, key=lambda c: c.rerank_score or 0.0, reverse=True),
            )
        )

    return sorted(result, key=lambda g: g.best_score, reverse=True)
