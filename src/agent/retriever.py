import logging
import math
import threading
from functools import lru_cache
from typing import Any

import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer

from src.agent.lexical import LexicalIndex, chunk_from_record, fuse
from src.agent.settings import settings
from src.api.schemas import ChunkResult, SourceGroup

logger = logging.getLogger(__name__)

# Taille des lots de lecture pour la construction de l'index lexical.
_LEXICAL_PAGE = 2000
# Recouvrement maximal cherché entre deux fenêtres consécutives d'un même
# élément. L'ingestion utilise 150 caractères ; la marge couvre un réglage
# différent sans rendre la recherche coûteuse.
_MAX_OVERLAP = 400


# ─── Singletons chargés une seule fois au démarrage ──────────────────────────

@lru_cache(maxsize=1)
def _get_embedding_model() -> SentenceTransformer:
    logger.info("Chargement du modèle d'embedding : %s", settings.embedding_model_name)
    model: SentenceTransformer = SentenceTransformer(settings.embedding_model_name)
    return model


@lru_cache(maxsize=1)
def _get_rerank_model() -> CrossEncoder:
    logger.info("Chargement du modèle de reranking : %s", settings.rerank_model)
    model: CrossEncoder = CrossEncoder(settings.rerank_model)
    return model


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


# ─── Index lexical BM25 ───────────────────────────────────────────────────────

_lexical_index = LexicalIndex()

# Reconstruction en cours, s'il y en a une. Un seul créneau : deux requêtes qui
# constatent la même dérive ne doivent pas lancer deux parcours du corpus.
_reconstruction: threading.Thread | None = None
_verrou_reconstruction = threading.Lock()
# Une reconstruction à la fois, tous appelants confondus. Distinct du verrou de
# `LexicalIndex` : celui-ci sérialise les constructions, celui-là les FUSIONNE.
# Sans lui, N appels à POST /reindex produisaient N parcours du corpus
# sérialisés, chacun occupant un fil du threadpool FastAPI pendant ~9 secondes —
# donc affamant les endpoints de recherche, qui vivent dans le même threadpool.
_verrou_reindexation = threading.Lock()


def _charger_corpus() -> tuple[list[str], list[str]]:
    """Lit tous les textes de la collection, par lots.

    C'est la partie coûteuse — linéaire dans la taille du corpus, mesurée à
    ~9 secondes sur celui de ce projet (§2, axes_amelioration.md). Elle est
    passée en rappel à `LexicalIndex.ensure` pour être exécutée SOUS SON
    VERROU : effectuée avant de le prendre, N requêtes concurrentes la
    payaient N fois.
    """
    collection = _get_chroma_collection()
    total = collection.count()
    chunk_ids: list[str] = []
    documents: list[str] = []

    offset = 0
    while offset < total:
        lot = collection.get(limit=_LEXICAL_PAGE, offset=offset, include=["documents"])
        chunk_ids.extend(lot.get("ids") or [])
        documents.extend(lot.get("documents") or [])
        offset += _LEXICAL_PAGE

    return chunk_ids, documents


def _taille_collection() -> int | None:
    """Nombre de chunks actuellement dans la collection, None s'il est illisible.

    L'absorption est LARGE parce que le client chromadb remonte des erreurs de
    transport, de sérialisation et de schéma sans ancêtre commun. Elle est MUETTE
    parce que ce qu'elle cache est déjà dit ailleurs : `ping()` sonde Chroma et
    /health publie le résultat dans la même réponse. Le doute est rendu tel
    quel — « je ne sais pas » — et jamais confondu avec « rien n'a changé ».
    """
    try:
        return int(_get_chroma_collection().count())
    except Exception:
        return None


def lexical_stale() -> bool:
    """L'index décrit-il un corpus qui n'existe plus ?

    L'ingestion est un service SÉPARÉ qui écrit dans ChromaDB pendant que
    l'agent tourne. Un document ingéré après la construction de l'index reste
    trouvable en recherche dense — la requête part à Chroma à chaque fois — et
    devenait invisible en recherche lexicale jusqu'au prochain redémarrage : la
    recherche devenait silencieusement asymétrique, tandis que /health
    continuait d'annoncer un index prêt. Il l'était ; il décrivait simplement
    un corpus disparu.

    Le compte de la collection est comparé au nombre de chunks indexés. Il est
    déjà lu au moment de la construction, donc la comparaison ne coûte rien de
    neuf. **Ce n'est qu'un filet** : un corpus dont on a retiré autant de chunks
    qu'on en a ajouté affiche le même compte. C'est pourquoi `POST /reindex`
    existe — un contrat que l'ingestion honore vaut mieux qu'une heuristique
    qu'elle ignore.
    """
    if not _lexical_index.ready:
        return False
    taille = _taille_collection()
    return taille is not None and taille != _lexical_index.size


def lexical_ready() -> bool:
    """L'index BM25 est-il construit ET à jour ? (exposé par /health)

    Un index périmé est déclaré NON prêt. Répondre vrai décrivait un corpus qui
    n'existait plus, ce qui est plus trompeur que d'admettre la dégradation :
    dans les deux cas la recherche est amputée, mais seul le faux le dit.
    """
    return _lexical_index.ready and not lexical_stale()


def rebuild_lexical_index() -> int:
    """Reconstruit l'index de force sur le corpus courant, et rend sa taille.

    Sert `POST /reindex` et la reconstruction de fond. `force` traverse le test
    « déjà prêt » d'`ensure` sans contourner son verrou : une recherche
    concurrente continue de lire l'ancien index jusqu'à ce que le nouveau le
    remplace d'un bloc.

    Les appels concurrents sont **fusionnés** et non sérialisés : celui qui
    arrive pendant une reconstruction attend son issue et rend sa taille, au lieu
    d'en enchaîner une seconde sur le même corpus. C'est ce qui distingue ce
    verrou de celui de `LexicalIndex` — sans lui, un appelant qui répète
    `POST /reindex` mobilise un fil du threadpool FastAPI par appel, pendant
    ~9 secondes chacun, et les endpoints de recherche partagent ce threadpool.
    """
    if not _verrou_reindexation.acquire(blocking=False):
        with _verrou_reindexation:
            return _lexical_index.size
    try:
        _lexical_index.ensure(_charger_corpus, force=True)
        return _lexical_index.size
    finally:
        _verrou_reindexation.release()


def _planifier_reconstruction() -> None:
    """Programme une reconstruction HORS du chemin de la requête.

    La lecture du corpus et la tokenisation coûtent ~9 secondes : les faire
    payer à la requête qui découvre la dérive punirait un utilisateur pour une
    ingestion à laquelle il n'a pas participé. L'index périmé continue de servir
    pendant ce temps — dégradé, mais pas absent, et il ne décrit alors qu'un
    corpus plus petit que le vrai.

    Fil démon : une reconstruction interrompue par l'arrêt du service ne laisse
    rien derrière elle — l'index n'est pas persisté — alors qu'un fil non démon
    retiendrait l'arrêt jusqu'à ~9 secondes.
    """
    global _reconstruction
    with _verrou_reconstruction:
        if _reconstruction is not None and _reconstruction.is_alive():
            return
        logger.info(
            "Index lexical périmé (%d chunks indexés, %s dans la collection) : "
            "reconstruction en tâche de fond, l'index actuel continue de servir.",
            _lexical_index.size,
            _taille_collection(),
        )
        _reconstruction = threading.Thread(
            target=rebuild_lexical_index, name="reindex-lexical", daemon=True
        )
        _reconstruction.start()


def _lexical_search(question: str, k: int) -> list[ChunkResult]:
    """Recherche BM25, résolue en ChunkResult via ChromaDB."""
    if not _lexical_index.ready:
        try:
            _lexical_index.ensure(_charger_corpus)
        except Exception:
            # Absorption LARGE et assumée : la recherche dense suffit à servir
            # la requête, et l'absence de BM25 dégrade le rappel sans casser la
            # réponse. Tracée avec sa pile, et /health la publie en
            # `index_lexical: false`.
            logger.exception("Index lexical indisponible, recherche dense seule.")
            return []
    elif lexical_stale():
        _planifier_reconstruction()

    hits = _lexical_index.search(question, k)
    if not hits:
        return []

    ids = [chunk_id for chunk_id, _ in hits]
    records = _get_chroma_collection().get(ids=ids, include=["documents", "metadatas"])
    par_id: dict[str, tuple[str, dict[str, Any]]] = {
        str(rid): (str(doc), dict(meta))
        for rid, doc, meta in zip(
            records.get("ids") or [],
            records.get("documents") or [],
            records.get("metadatas") or [],
            strict=False,
        )
    }
    # L'ordre du classement BM25 est ce qui compte pour la fusion : on le
    # préserve au lieu de reprendre celui, arbitraire, du `get`.
    return [
        chunk_from_record(chunk_id, *par_id[chunk_id]) for chunk_id, _ in hits if chunk_id in par_id
    ]


def full_texts(element_ids: list[str]) -> dict[str, str]:
    """Recompose le texte intégral des éléments demandés depuis ChromaDB.

    Le graphe ne porte qu'un aperçu : l'ingestion y tronque le texte à 2000
    caractères, le corpus complet vivant dans l'index vectoriel. Un tableau
    exporté par Docling dépasse souvent cette limite et arrivait donc amputé au
    LLM — alors que sa version entière était à un `get` de distance.

    Un élément long est réparti sur plusieurs chunks recouvrants (`abc#0`,
    `abc#1`, …) : ils sont remis dans l'ordre puis recollés en retirant le
    recouvrement, sinon la jointure dupliquerait la charnière.

    Args:
        element_ids: Identifiants d'éléments (hash 10 hexadécimaux).

    Returns:
        Dict {element_id: texte complet}. Les éléments absents de l'index —
        titres, fragments trop courts pour être vectorisés — sont omis.
    """
    if not element_ids:
        return {}

    try:
        records = _get_chroma_collection().get(
            where={"element_id": {"$in": list(set(element_ids))}},  # type: ignore[dict-item]
            include=["documents", "metadatas"],
        )
    except Exception:
        # Absorption LARGE et assumée : le client chromadb remonte transport,
        # sérialisation et schéma sans ancêtre commun. La dégradation est réelle
        # mais bornée — le texte tronqué du graphe reste, donc le LLM reçoit un
        # tableau amputé plutôt que rien — et elle est tracée en WARNING.
        logger.warning("Texte intégral indisponible, le texte du graphe est conservé.")
        return {}

    par_element: dict[str, list[tuple[int, str]]] = {}
    for doc, meta in zip(
        records.get("documents") or [], records.get("metadatas") or [], strict=False
    ):
        eid = str(meta.get("element_id") or "")
        if eid:
            index = int(str(meta.get("chunk_index") or 0))
            par_element.setdefault(eid, []).append((index, doc or ""))

    return {
        eid: _join_overlapping([texte for _, texte in sorted(morceaux)])
        for eid, morceaux in par_element.items()
    }


def _join_overlapping(morceaux: list[str]) -> str:
    """Recolle des fenêtres recouvrantes en supprimant la partie commune.

    L'ingestion découpe avec un recouvrement (150 caractères par défaut) : une
    concaténation naïve répéterait la charnière. On cherche le plus long suffixe
    du texte accumulé qui soit préfixe du morceau suivant.
    """
    if not morceaux:
        return ""

    resultat = morceaux[0]
    for morceau in morceaux[1:]:
        limite = min(len(resultat), len(morceau), _MAX_OVERLAP)
        recouvrement = 0
        for taille in range(limite, 0, -1):
            if resultat.endswith(morceau[:taille]):
                recouvrement = taille
                break
        resultat += morceau[recouvrement:] if recouvrement else f" {morceau}"
    return resultat


def ping() -> bool:
    """Vérifie que ChromaDB répond (utilisé par /health).

    Absorption LARGE et assumée : une sonde ne doit jamais lever. Elle n'est pas
    muette — le faux rendu ici est ce que /health publie — et elle agit : le
    cache de collection est oublié, pour que la prochaine requête rouvre.
    """
    try:
        _get_chroma_collection().count()
        return True
    except Exception:
        reset_connection()
        return False


# ─── Retrieval ────────────────────────────────────────────────────────────────

def retrieve(
    question: str, top_k: int | None = None, translation: str | None = None
) -> list[ChunkResult]:
    """Recherche les candidats et fusionne tout ce qui a été trouvé.

    Jusqu'à quatre classements entrent dans la fusion : dense et lexical, pour
    la question et pour sa traduction. Chacun ramène FETCH_K candidats et la
    fusion RRF n'en garde que top_k — élargir en amont est ce qui donne à la
    fusion de quoi travailler, deux listes identiques ne fusionnent rien.

    Args:
        question: La question, dans sa langue d'origine.
        top_k: Candidats conservés après fusion.
        translation: La même question dans l'autre langue du corpus. Elle
            n'existe que pour la recherche : la génération ne la voit jamais.
    """
    k = top_k or settings.retrieval_top_k
    if not settings.hybrid_search and not translation:
        return _dense_search(question, k)[:k]

    requetes = [(question, 1.0)]
    if translation:
        # La traduction pèse moins : elle sauve les questions dont le document
        # est dans l'autre langue, mais ramène du bruit sur les autres.
        requetes.append((translation, settings.translation_weight))

    # La recherche dense d'abord : elle seule porte une distance vectorielle
    # réelle, et fait donc foi sur les métadonnées d'un chunk vu deux fois.
    classements: list[list[ChunkResult]] = []
    poids: list[float] = []
    for requete, poids_requete in requetes:
        classements.append(_dense_search(requete, settings.fetch_k))
        poids.append(poids_requete)
    if settings.hybrid_search:
        for requete, poids_requete in requetes:
            classements.append(_lexical_search(requete, settings.fetch_k))
            poids.append(poids_requete)

    retenus = [(c, p) for c, p in zip(classements, poids, strict=True) if c]
    if not retenus:
        return []
    non_vides = [c for c, _ in retenus]

    fusionnes = fuse(non_vides, k, poids=[p for _, p in retenus])
    logger.info(
        "Recherche : %s → %d fusionnés pour %r%s",
        " + ".join(str(len(c)) for c in non_vides),
        len(fusionnes),
        question[:44],
        " (+ traduction)" if translation else "",
    )
    return fusionnes


def _dense_search(question: str, k: int) -> list[ChunkResult]:
    """Recherche vectorielle seule."""
    embedding_model = _get_embedding_model()
    collection = _get_chroma_collection()

    query_embedding: list[float] = embedding_model.encode(question).tolist()

    def _query(coll: chromadb.Collection) -> dict[str, Any]:
        return dict(coll.query(
            query_embeddings=[query_embedding],  # type: ignore[arg-type]
            n_results=k,
            include=["documents", "metadatas", "distances"],
        ))

    try:
        results = _query(collection)
    except Exception:
        # La collection est mise en cache : si ChromaDB a redémarré, l'objet
        # pointe vers une connexion morte et toutes les recherches échouent
        # jusqu'au redémarrage de l'agent. On la rouvre et on retente une fois.
        # Absorption LARGE parce qu'un client mort produit des erreurs de
        # transport, de sérialisation et de schéma sans ancêtre commun ; tracée
        # en WARNING, et un second échec remonte à l'appelant.
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

    logger.debug("Dense : %d chunks pour '%s'", len(chunks), question[:60])
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
    # Les stubs du cross-encoder décrivent un type d'entrée multimodal très
    # large ; une liste de paires texte est ce qu'il accepte en pratique.
    scores: list[float] = rerank_model.predict(pairs).tolist()  # type: ignore[arg-type]

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
