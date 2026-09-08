import logging
import math
import threading
from functools import lru_cache
from typing import Any

import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer

from src.agent.chronometrie import Chrono
from src.agent.lexical import LexicalIndex, chunk_from_record, fuse
from src.agent.settings import settings
from src.api.schemas import ChunkResult, EmbeddingModelHealth, SourceGroup

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
    """Oublie la collection mise en cache, pour la rouvrir au prochain appel.

    Réarme aussi le verdict de concordance : la collection rouverte peut être
    une AUTRE collection — une réingestion a pu passer entre-temps — donc un
    verdict établi sur la précédente ne vaut plus rien.

    L'ORDRE DE CES DEUX LIGNES PORTE, ET IL EST GARDÉ. `cache_clear()` d'abord,
    `rearmer_verification_modele()` ensuite. Inversés, ils réintroduisent B2 à
    l'identique — un verdict favorable MÉMORISÉ sur une collection divergente —
    par le seul entrelacement suivant :

        1. `rearmer_verification_modele()` : la génération passe à G+1 ;
        2. un autre fil vérifie : il relève G+1, puis lit l'estampille — le cache
           n'est PAS encore vidé, donc il lit l'ANCIENNE collection, concordante ;
        3. `cache_clear()` : la prochaine ouverture rendra la NOUVELLE collection,
           que rien ne garantit concordante ;
        4. le fil vérificateur conclut : la génération n'a pas bougé depuis qu'il
           l'a relevée, donc il inscrit son verdict favorable. Ce verdict décrit
           une collection que personne ne lira plus.

    Le compare-et-échange ne peut rien contre cet ordre-là, et c'est le point : il
    protège contre un réarmement survenu PENDANT la lecture, pas contre un
    réarmement survenu AVANT une lecture qui porte encore sur l'ancien cache. Dans
    le bon ordre, la lecture qui suit le vidage ouvre la nouvelle collection et
    voit la divergence ; celle qui l'a précédé voit sa génération bouger et JETTE
    son verdict. Les deux issues sont sûres.

    **`mesuré` : inversées, les 552 tests de la campagne restaient VERTS.** Une
    décision argumentée et non gardée est une décision qui se défera sans un
    rouge — et celle-ci protège exactement le bloquant que ce lot existe pour
    fermer. Garde : `tests/unit/test_garde_modele_embedding.py`,
    `test_l_ordre_de_reset_connection_ne_peut_pas_s_inverser_en_silence`.
    """
    _get_chroma_collection.cache_clear()
    rearmer_verification_modele()


# ─── Le garde du modèle d'embedding ──────────────────────────────────────────
#
# LA PANNE. Les deux modèles candidats du projet rendent des vecteurs de la même
# largeur — 384 dimensions, site canonique `documentation/axes_amelioration.md`
# §4.4. ChromaDB accepte donc sans broncher un index produit par l'un et
# interrogé par l'autre : pas d'exception, pas de ligne de journal, aucune sonde
# de forme qui voie quoi que ce soit. La recherche rend simplement des passages
# PLAUSIBLES ET FAUX. Vérifier la dimension ne protège de rien ; c'est le NOM
# qui discrimine, et c'est déjà arrivé une fois sur ce système.
#
# CE QUI REND LE GARDE POSSIBLE. Le pipeline d'ingestion estampille la
# collection : `collection.metadata["embedding_model"]` porte le nom du modèle
# qui a produit les vecteurs. Le producteur avait fait sa moitié ; ceci est
# celle du lecteur.
#
# CE QUE LA LECTURE COÛTE, ET C'EST POURQUOI ELLE PEUT VIVRE SUR LE CHEMIN DE
# CHAQUE RECHERCHE. `Collection.metadata` est une propriété LOCALE du client
# chromadb (1.5.9 : `return self._model.metadata`), remplie au `get_collection`.
# La lire ne fait aucun aller-retour — contrairement à `count()`, qui en fait un
# et dont `lexical_stale` paie le prix à chaque appel.
#
# CE QUE CETTE ÉCONOMIE COÛTE EN RETOUR, et c'est une réserve, pas un détail :
# l'estampille lue est celle capturée à l'ouverture de la collection. Une
# réingestion qui changerait de modèle pendant que l'agent tourne ne serait vue
# qu'après `reset_connection()` — donc après une panne de Chroma, ou un
# redémarrage. Le pipeline ne réingère pas sous l'agent sans que quelqu'un le
# sache ; ce qui reste ouvert est consigné dans le rapport du lot.

class EmbeddingModelMismatchError(RuntimeError):
    """La collection n'a pas été produite par le modèle avec lequel on la lit.

    Ou bien on ne sait pas ce qui l'a produite, ce qui revient au même : dans les
    deux cas, rien ne permet d'affirmer que les vecteurs de la question et ceux
    de l'index vivent dans le même espace.
    """


# Verdict favorable déjà établi. Seul le FAVORABLE est retenu : un refus est
# re-mesuré à chaque appel, pour qu'une réparation soit visible sans avoir à
# redémarrer, et parce qu'on ne sert rien pendant ce temps de toute façon.
#
# CE QUE CE SITE A AFFIRMÉ, ET QUI ÉTAIT FAUX. Il portait que « le pire cas est
# une vérification faite deux fois — un verrou coûterait plus cher que ce qu'il
# éviterait ». C'est une PERTE DE MISE À JOUR, mesurée :
# `verifier_modele_embedding()` lit l'estampille, puis écrit le verdict À LA
# FIN ; un `rearmer_verification_modele()` arrivé entre les deux était écrasé par
# cette écriture. La conséquence n'est pas une vérification en trop, c'est un
# garde DÉSARMÉ pour toute la vie du processus, servant des passages plausibles
# et faux en silence. Site canonique :
# `documentation/axes_amelioration.md` §4.20, trouvaille B2.
#
# ATTEIGNABLE, et c'est ce qui en faisait un bloquant : `reset_connection()`
# tourne dans un fil du threadpool depuis le `ping()` du healthcheck, toutes les
# 20 s, et depuis la reprise de `_dense_search`, pendant que d'autres fils
# vérifient.
#
# CE QUI TIENT LA PLACE DU VERROU SUR LE CHEMIN CHAUD. Une GÉNÉRATION, incrémentée
# à chaque réarmement. La vérification la relève avant de lire, et n'inscrit son
# verdict favorable que si elle n'a pas bougé — un compare-et-échange. Le verrou
# ne couvre donc que deux affectations en mémoire, jamais la lecture : un
# réarmement concurrent n'attend pas derrière l'ouverture d'une collection, et un
# réarmement survenu pendant la lecture fait JETER le verdict plutôt que l'écraser.
# Se tromper dans ce sens-là coûte une relecture locale ; se tromper dans l'autre
# coûte le garde.
_verrou_concordance = threading.Lock()
_concordance_etablie = False
_generation_concordance = 0


def rearmer_verification_modele() -> None:
    """Oublie le verdict favorable, pour que la prochaine lecture le refasse.

    Incrémente la génération : une vérification déjà en cours de lecture verra
    que le monde a bougé sous elle et renoncera à inscrire son verdict.
    """
    global _concordance_etablie, _generation_concordance
    with _verrou_concordance:
        _concordance_etablie = False
        _generation_concordance += 1


def _lire_estampille() -> str | None:
    """Le nom du modèle qui a produit la collection, None s'il n'est pas inscrit.

    LÈVE si le store est illisible, et c'est voulu : « je n'ai pas pu lire » ne
    doit jamais se confondre avec « la collection ne porte pas d'estampille ».
    Le premier est un fait sur ChromaDB, le second un fait sur ce qui a indexé.
    """
    metadata = _get_chroma_collection().metadata or {}
    estampille = metadata.get("embedding_model")
    return str(estampille) if estampille is not None else None


def verifier_modele_embedding() -> None:
    """Refuse de lire une collection qu'un autre modèle a produite.

    Appelée en tête de la recherche dense, AVANT tout chargement de modèle : le
    constructeur `SentenceTransformer` télécharge ce qui manque au cache, et un
    garde placé après paierait le rapatriement du mauvais modèle avant de le
    refuser.

    Une estampille ABSENTE est refusée comme une divergence. C'est la décision du
    lot, et c'est le cœur du problème : un garde qui ne comparerait que lorsque
    l'estampille est présente serait décoratif sur exactement le cas où l'on ne
    sait pas ce qui a indexé. Le prix est réel — une collection produite par un
    pipeline plus ancien n'en porte pas, et l'agent la refusera — et il est
    payé sciemment : le geste de réparation est court et nommé dans le message,
    alors qu'un index lu de travers ne se voit qu'en relisant les réponses une
    par une.

    Une estampille ILLISIBLE n'est pas refusée ici : l'erreur du store remonte
    telle quelle. La recherche échouera de toute façon, et masquer une panne de
    ChromaDB derrière une erreur de configuration enverrait chercher au mauvais
    endroit.
    """
    global _concordance_etablie
    with _verrou_concordance:
        if _concordance_etablie:
            return
        generation = _generation_concordance
    attendu = settings.embedding_model_name
    estampille = _lire_estampille()
    if estampille is None:
        raise EmbeddingModelMismatchError(
            f"La collection '{settings.chroma_collection}' ne porte aucune estampille "
            f"`embedding_model` : rien ne dit avec quel modèle elle a été indexée, et "
            f"l'agent s'apprête à la lire avec '{attendu}'. Les modèles candidats de ce "
            f"projet rendent des vecteurs de même largeur, donc une erreur ici ne "
            f"produirait aucune exception, seulement des passages plausibles et faux. "
            f"Réparation : réingérer avec le pipeline courant, qui estampille, ou "
            f"inscrire l'estampille sur la collection si l'on sait ce qui l'a produite."
        )
    if estampille != attendu:
        raise EmbeddingModelMismatchError(
            f"La collection '{settings.chroma_collection}' a été indexée avec "
            f"'{estampille}', et l'agent s'apprête à la lire avec '{attendu}'. Les deux "
            f"rendent des vecteurs de même largeur : ChromaDB ne s'en plaindra pas et la "
            f"recherche rendra des passages plausibles et faux. Réparation : aligner "
            f"EMBEDDING_MODEL_NAME sur '{estampille}', ou réingérer avec '{attendu}'."
        )
    with _verrou_concordance:
        # Le compare-et-échange. Si la génération a bougé pendant la lecture,
        # un `reset_connection()` est passé : le verdict qu'on tient décrit une
        # collection dont plus rien ne garantit qu'elle est encore celle-là, et
        # l'inscrire ÉCRASERAIT le réarmement. On le jette, la prochaine
        # recherche relira — c'est une lecture locale, elle ne coûte rien.
        if generation == _generation_concordance:
            _concordance_etablie = True


def etat_modele_embedding() -> EmbeddingModelHealth:
    """Le même fait, sous la forme d'un rapport plutôt que d'un refus.

    Sert `/health` et le démarrage. Ne lève JAMAIS : une sonde qui tombe fait
    tomber la route qui la porte, et `/health` doit répondre 200 même dégradé.

    LE MOTIF, ET C'EST LE VRAI. Ce docstring a porté que `/health` devait rendre
    200 « sous peine de faire redémarrer le service en boucle ». C'est FAUX,
    mesuré deux fois indépendamment : un healthcheck en échec ne redéclenche
    aucun conteneur sous Docker Compose — `restart:` répond à la SORTIE du
    processus, pas à la santé — et 21 échecs consécutifs laissent
    `RestartCount=0` et `StartedAt` inchangé. Ce qui arrive vraiment est que le
    conteneur passe `unhealthy`, donc que `frontend`, qui en dépend en
    `condition: service_healthy` (`docker-compose.yml`), ne lève pas au démarrage
    à froid : une panne lisible deviendrait une pile muette. Le trou reste
    acceptable, mais sur ce motif-là. Site canonique :
    `documentation/axes_amelioration.md` §1.27 et §4.20, trouvaille N2.

    L'absorption est LARGE — le client chromadb remonte des erreurs de transport,
    de sérialisation et de schéma sans ancêtre commun, cf. `_taille_collection` —
    et elle n'est pas muette : ce qu'elle attrape devient `unknown`, publié comme
    tel dans la réponse, et le démarrage le journalise en WARNING.
    """
    attendu = settings.embedding_model_name
    try:
        estampille = _lire_estampille()
    except Exception:
        return EmbeddingModelHealth(status="unknown", expected=attendu, collection=None)
    if estampille is None:
        return EmbeddingModelHealth(status="missing", expected=attendu, collection=None)
    if estampille != attendu:
        return EmbeddingModelHealth(status="mismatch", expected=attendu, collection=estampille)
    return EmbeddingModelHealth(status="ok", expected=attendu, collection=estampille)


# ─── Index lexical BM25 ───────────────────────────────────────────────────────

_lexical_index = LexicalIndex()

# Reconstruction en cours, s'il y en a une. Un seul créneau : deux requêtes qui
# constatent la même dérive ne doivent pas lancer deux parcours du corpus.
_reconstruction: threading.Thread | None = None
_verrou_reconstruction = threading.Lock()
# Une reconstruction à la fois, tous appelants confondus. Distinct du verrou de
# `LexicalIndex` : celui-ci sérialise les constructions, celui-là les FUSIONNE.
# Sans lui, N appels à POST /reindex produisaient N parcours du corpus
# sérialisés, chacun occupant un fil du threadpool FastAPI le temps d'un parcours
# complet (~9 s, non mesuré — cf. `_charger_corpus`) —
# donc affamant les endpoints de recherche, qui vivent dans le même threadpool.
_verrou_reindexation = threading.Lock()


def _charger_corpus() -> tuple[list[str], list[str]]:
    """Lit tous les textes de la collection, par lots.

    C'est la partie coûteuse, linéaire dans la taille du corpus : tout le corpus
    est lu par lots de `_LEXICAL_PAGE`, puis tokenisé.

    **Le « ~9 s » écrit ailleurs dans ce dépôt n'est PAS une mesure** — c'est un
    ordre de grandeur hérité de la documentation d'origine, qu'aucune exécution
    n'a produit. La réserve et le protocole de mesure sont au site canonique,
    axes_amelioration.md §2 « Index BM25 en mémoire ». Ce qui est
    structurellement vrai, et qui suffit à justifier ce qui l'entoure : ce
    parcours est long devant une requête.

    Elle est passée en rappel à `LexicalIndex.ensure` pour être exécutée SOUS SON
    VERROU : effectuée avant de le prendre, N requêtes concurrentes la payaient
    N fois.
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

    Le compte de la collection est comparé au nombre de chunks indexés.

    **Ce que cette comparaison coûte, et ce n'est pas rien.** Un aller-retour
    ChromaDB par appel : mesuré au compteur, 10 recherches lexicales font 10
    `count()`, et 5 appels à `lexical_ready` — donc 5 sondes /health — en font 5.
    Une version antérieure de ce docstring affirmait que « le compte est déjà lu
    au moment de la construction, donc la comparaison ne coûte rien de neuf » :
    c'est faux, la lecture de la construction ne sert qu'à la construction. Un
    cache sur fenêtre courte est un candidat, mais c'est un arbitrage de
    performance qui demande une mesure contre les vrais stores — il est ouvert
    dans axes_amelioration.md, pas décidé ici.

    **Ce n'est qu'un filet** : un corpus dont on a retiré autant de chunks qu'on
    en a ajouté affiche le même compte. C'est pourquoi `POST /reindex` existe —
    un contrat que l'ingestion honore vaut mieux qu'une heuristique qu'elle
    ignore.
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
    `POST /reindex` mobilise un fil du threadpool FastAPI par appel, le temps d'un
    parcours complet chacun (~9 s, non mesuré — cf. `_charger_corpus`), et les
    endpoints de recherche partagent ce threadpool.
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

    La lecture du corpus et la tokenisation coûtent ~9 secondes (chiffre non
    mesuré, cf. `_charger_corpus`) : les faire payer à la requête qui découvre la
    dérive punirait un utilisateur pour une ingestion à laquelle il n'a pas
    participé. L'index périmé continue de servir
    pendant ce temps — dégradé, mais pas absent, et il ne décrit alors qu'un
    corpus plus petit que le vrai.

    Fil démon : une reconstruction interrompue par l'arrêt du service ne laisse
    rien derrière elle — l'index n'est pas persisté — alors qu'un fil non démon
    retiendrait l'arrêt jusqu'à la fin du parcours.
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
    question: str,
    top_k: int | None = None,
    translation: str | None = None,
    chrono: Chrono | None = None,
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
        chrono: Accumulateur d'étages. Renseigné, il reçoit `dense_ms`,
            `lexical_ms` et `fusion_ms` séparément — sans quoi les trois
            restent noyés dans le temps mural du nœud, et « dense seul vs
            hybride » ne peut pas s'arbitrer sur le prix. Absent, la fonction
            ne mesure rien : le banc de réglage n'en a pas besoin.
    """
    chrono = chrono or Chrono()
    k = top_k or settings.retrieval_top_k
    if not settings.hybrid_search and not translation:
        with chrono.mesurer("dense_ms"):
            dense = _dense_search(question, k)
        return dense[:k]

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
        with chrono.mesurer("dense_ms"):
            classements.append(_dense_search(requete, settings.fetch_k))
        poids.append(poids_requete)
    if settings.hybrid_search:
        for requete, poids_requete in requetes:
            with chrono.mesurer("lexical_ms"):
                classements.append(_lexical_search(requete, settings.fetch_k))
            poids.append(poids_requete)

    retenus = [(c, p) for c, p in zip(classements, poids, strict=True) if c]
    if not retenus:
        return []
    non_vides = [c for c, _ in retenus]

    with chrono.mesurer("fusion_ms"):
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
    """Recherche vectorielle seule.

    La concordance du modèle est vérifiée ICI, avant le moindre chargement : ce
    site est celui qui PRODUIT le comportement à empêcher — une collection
    interrogée avec le mauvais embedder — et il est le seul que tout chemin de
    recherche traverse. Un agent démarré avant une réingestion divergente, ou
    démarré alors que ChromaDB ne répondait pas, ne passe par aucun garde de
    démarrage ; il passe par celui-ci.
    """
    verifier_modele_embedding()
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
        # LE GARDE EST REPASSÉ ICI, et ce n'est pas une précaution abstraite.
        # `reset_connection()` a désarmé le verdict précisément parce que la
        # collection rouverte peut être une AUTRE collection — et une coupure de
        # ChromaDB est exactement le moment où une réingestion a pu passer
        # dessous. Sans cette ligne, la requête en cours interrogeait la
        # collection neuve SANS repasser le garde : une réponse complète et
        # FAUSSE, sans exception ni ligne de journal, sur le seul chemin où
        # l'objet collection change d'identité en vol. Mesuré, et site canonique
        # `documentation/axes_amelioration.md` §4.20, trouvaille B1.
        # Garde : tests/unit/test_garde_modele_embedding.py,
        # `test_la_reprise_apres_reouverture_repasse_le_garde`.
        verifier_modele_embedding()
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
