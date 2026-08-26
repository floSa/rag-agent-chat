"""Capture d'usage : ce qui a été demandé, ce qui a été proposé, ce qui a été retenu.

Le dépôt n'enregistrait rien de ce qu'il servait. La conséquence n'est pas
seulement l'absence de piste d'audit : c'est l'absence de la seule vérité
terrain non biaisée qui puisse exister. Le jeu doré est **généré** depuis le
corpus et jamais relu ; quand un utilisateur décoche une source que le reranker
avait classée deuxième avec 0,81 de pertinence, il produit gratuitement
l'annotation négative qu'aucune génération automatique ne sait fabriquer.

Trois usages dictent la forme des deux tables, et rien d'autre :

1. **Les décochages** — une ligne par source PROPOSÉE, avec son rang, sa
   pertinence et son sort. C'est ce qui rend la question « quelles sources bien
   classées les gens écartent-ils ? » soluble en une requête SQL.
2. **Un jeu doré réel** — les questions réellement posées, les sources validées
   par un humain, et son appréciation de la réponse.
3. **La distribution des classes de questions** — d'où la question stockée
   telle qu'elle a été posée, sans normalisation.

Trois contraintes de conception, qui expliquent la forme du code :

- **Un échec de capture ne fait jamais échouer une requête.** Chaque point
  d'entrée absorbe ses exceptions et journalise en WARNING. C'est de
  l'observation, pas une fonctionnalité.
- **Rien n'est écrit dans le chemin de diffusion.** Les écritures ont lieu
  après le dernier événement SSE, via aiosqlite — donc hors de la boucle
  d'événements pour la partie bloquante.
- **Aucune purge.** C'est un jeu de données, pas un cache : le vider serait
  détruire l'actif. En échange, sa taille est visible (démarrage et /health).

Ce qui n'est PAS fait, et qui doit être su : **aucune détection de données
personnelles**. Une question saisie par un utilisateur peut en contenir ; elle
est stockée telle quelle. Cf. documentation/SECURITY.md.
"""

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import aiosqlite

# Le condensat doit porter sur le dossier que la GÉNÉRATION lit réellement.
# `settings.prompts_dir` vaut le chemin monté dans l'image ; hors conteneur il
# n'existe pas et llm.py se replie sur celui du dépôt. Réimplémenter ce repli
# ici produirait une empreinte qui affirme « prompt inchangé » alors que le
# prompt a changé — exactement le défaut que ce champ existe pour empêcher.
from src.agent.llm import _prompts_dir
from src.agent.settings import settings
from src.api.schemas import ChunkResult, Citation, ImageRef, SectionContext, UsageStats

logger = logging.getLogger(__name__)

# Version du schéma des deux tables. Exportée avec les données : un
# enregistrement dont on ne sait pas quelles colonnes existaient est illisible.
# Elle suit la forme des LIGNES, pas les vues de lecture : celles-ci sont
# (re)créées à chaque connexion, donc une base plus ancienne les reçoit sans
# que ses enregistrements changent de forme.
SCHEMA_VERSION = 1

# Attente avant de renoncer quand une autre connexion tient la base. SQLite
# sérialise les écritures : sans ce délai, deux interactions simultanées se
# soldent par un « database is locked » immédiat, donc par une observation
# perdue là où une milliseconde d'attente suffisait.
_VERROU_TIMEOUT_S = 5.0

# Nombre d'échecs de capture depuis le démarrage, et palier de rappel. Le motif
# `except Exception: logger.debug(...)` du dépôt a déjà caché un défaut pendant
# tout un lot : ici le premier échec est un WARNING, et le compteur est exposé
# dans /health.
_echecs = 0
_PALIER_RAPPEL = 100

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS interactions (
        thread_id             TEXT PRIMARY KEY,
        -- 'chat' (flux interactif, seul à porter une sélection humaine),
        -- 'answer' (chemin d'évaluation), 'chat_simple' (génération directe).
        -- Toute lecture des décochages DOIT filtrer là-dessus.
        endpoint              TEXT NOT NULL,
        started_at            TEXT NOT NULL,
        completed_at          TEXT,
        question              TEXT NOT NULL,
        search_query          TEXT,
        search_translation    TEXT,
        ranked_element_ids    TEXT NOT NULL DEFAULT '[]',
        submitted_element_ids TEXT,
        submitted_section_ids TEXT,
        response              TEXT,
        citations             TEXT,
        images                TEXT,
        search_count          INTEGER,
        dropped_contexts      INTEGER,
        retrieval_ms          INTEGER,
        rerank_ms             INTEGER,
        generation_ms         INTEGER,
        config_hash           TEXT NOT NULL,
        config_json           TEXT NOT NULL,
        rating                TEXT,
        rating_comment        TEXT,
        rated_at              TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources_proposees (
        thread_id     TEXT NOT NULL,
        rang          INTEGER NOT NULL,
        element_id    TEXT NOT NULL,
        filename      TEXT NOT NULL DEFAULT '',
        collection    TEXT NOT NULL DEFAULT '',
        source_path   TEXT NOT NULL DEFAULT '',
        section_title TEXT NOT NULL DEFAULT '',
        language      TEXT NOT NULL DEFAULT '',
        page_no       INTEGER,
        relevance     REAL,
        rerank_score  REAL,
        -- 1 retenue, 0 écartée, NULL la sélection n'a jamais eu lieu. Les trois
        -- états sont distincts : compter un abandon comme un décochage
        -- fabriquerait une annotation négative que personne n'a produite.
        retenue       INTEGER,
        PRIMARY KEY (thread_id, element_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sources_retenue ON sources_proposees (retenue, rang)",
    "CREATE INDEX IF NOT EXISTS idx_interactions_endpoint ON interactions (endpoint, started_at)",
    # Les sources qu'un HUMAIN a vues et arbitrées. Le filtre sur `endpoint`
    # était une convention documentée, et une convention ne survit pas à une
    # requête écrite de mémoire dans six mois : /answer retient
    # AUTO_SELECT_TOP_K sources et écrit `retenue = 0` sur toutes les autres,
    # soit trois faux décochages par question, mille par campagne, indiscernables
    # d'un décochage humain. Ces deux vues rendent l'erreur impossible plutôt
    # que déconseillée.
    """
    CREATE VIEW IF NOT EXISTS sources_humaines AS
        SELECT s.*, i.question, i.started_at, i.rating
        FROM   sources_proposees s
        JOIN   interactions      i USING (thread_id)
        WHERE  i.endpoint = 'chat'
    """,
    # Nommée par ce qu'elle contient, et rien d'autre : une vue « décochages »
    # qui rendrait aussi les sources retenues serait un second piège de la même
    # espèce que celui qu'on ferme.
    """
    CREATE VIEW IF NOT EXISTS decochages AS
        SELECT * FROM sources_humaines WHERE retenue = 0
    """,
    # Version du schéma inscrite DANS le fichier : un export doit dire quelles
    # colonnes existaient, pas quelles colonnes le code d'aujourd'hui connaît.
    f"PRAGMA user_version = {SCHEMA_VERSION}",
)


def capture_active() -> bool:
    """Vrai si la capture est demandée et a un fichier où écrire."""
    return settings.usage_capture and bool(settings.usage_db_path)


def _maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _echec(operation: str, exc: BaseException) -> None:
    """Journalise un échec de capture — au moins une fois, sans inonder.

    Le premier échec sort en WARNING avec sa trace, puis un rappel tous les
    `_PALIER_RAPPEL`. Une base verrouillée peut échouer à chaque requête : un
    WARNING par requête noierait le journal et ferait perdre le reste.
    """
    global _echecs
    _echecs += 1
    if _echecs == 1 or _echecs % _PALIER_RAPPEL == 0:
        logger.warning(
            "Capture d'usage : %s a échoué (%d échec(s) depuis le démarrage). "
            "L'observation est perdue, la requête est servie normalement.",
            operation,
            _echecs,
            exc_info=exc,
        )


def _condensat_prompts() -> str:
    """Condensat du CONTENU de prompts/, pour rendre un prompt attribuable.

    Sans lui, une modification de prompt n'est attribuable dans aucune campagne
    ni aucun enregistrement : deux réponses différentes portent la même
    configuration apparente.

    Pas de cache : quatre lectures de petits fichiers par interaction, contre
    une requête qui dure des secondes. Un cache exigerait une invalidation sur
    mtime, et une empreinte périmée est précisément le défaut que ce champ
    existe pour empêcher.

    Parcours RÉCURSIF, et le chemin relatif entre dans le condensat plutôt que
    le seul nom de fichier. `prompts/` est plat aujourd'hui : un simple
    `iterdir` marche, jusqu'au jour où quelqu'un y range un gabarit dans un
    sous-dossier — l'empreinte affirmerait alors « prompt inchangé » sur un
    prompt modifié, c'est-à-dire exactement ce que ce champ existe pour
    empêcher. Le chemin, et non le nom, pour que déplacer un gabarit d'un
    dossier à l'autre se voie.
    """
    hacheur = hashlib.sha256()
    dossier = _prompts_dir()
    fichiers = sorted(
        (p.relative_to(dossier).as_posix(), p) for p in dossier.rglob("*") if p.is_file()
    )
    for chemin_relatif, fichier in fichiers:
        hacheur.update(chemin_relatif.encode("utf-8"))
        hacheur.update(fichier.read_bytes())
    return hacheur.hexdigest()[:12]


def configuration() -> tuple[str, dict[str, Any]]:
    """Empreinte de la configuration qui a produit l'interaction.

    Un enregistrement sans la configuration qui l'a produit est illisible dans
    six mois : on ne sait plus si l'écart vient du corpus, du réglage ou du
    prompt. Le détail est stocké en JSON, le hash court sert à grouper.
    """
    detail: dict[str, Any] = {
        "embedding_model": settings.embedding_model_name,
        "rerank_model": settings.rerank_model,
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_top_k": settings.rerank_top_k,
        "translation_weight": settings.translation_weight,
        "llm_num_ctx": settings.llm_num_ctx,
        "llm_max_tokens": settings.llm_max_tokens,
        "ollama_model": settings.ollama_model,
        "prompts_sha256": _condensat_prompts(),
    }
    serialise = json.dumps(detail, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialise.encode("utf-8")).hexdigest()[:12], detail


@asynccontextmanager
async def _connexion() -> AsyncIterator[aiosqlite.Connection]:
    """Ouvre la base, garantit le schéma, valide à la sortie.

    Une connexion par écriture : elle vit le temps d'une transaction, ce qui
    évite de partager un objet lié à une boucle d'événements entre requêtes —
    le piège qui avait déjà fait tomber le checkpointer.
    """
    chemin = Path(settings.usage_db_path)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # `isolation_level=None` : aucune transaction implicite, chaque écriture
    # ouvre la sienne. C'est le `BEGIN IMMEDIATE` plus bas qui rend une capture
    # ATOMIQUE — sans lui, l'interaction et ses sources partiraient en deux
    # transactions séparées, et un arrêt entre les deux laisserait une
    # interaction sans son classement. Il prend de plus le verrou d'écriture
    # d'entrée : une transaction *deferred* qui promeut son verrou de lecture
    # reçoit un SQLITE_BUSY que le délai d'attente ne rejoue pas (comportement
    # documenté de SQLite). Ce second point est une précaution, pas un
    # correctif : mesuré, il n'est pas ce à quoi la perte d'écritures
    # simultanées était imputable — c'était le mode de journalisation, cf.
    # `initialiser`.
    async with aiosqlite.connect(
        chemin, timeout=_VERROU_TIMEOUT_S, isolation_level=None
    ) as conn:
        # Avant tout le reste : c'est ce délai qui fait attendre le CREATE et le
        # BEGIN ci-dessous au lieu de les faire échouer.
        await conn.execute(f"PRAGMA busy_timeout = {int(_VERROU_TIMEOUT_S * 1000)}")
        # La capture est de l'observation : perdre la dernière transaction lors
        # d'une coupure de courant est acceptable, faire attendre une requête le
        # temps d'un fsync ne l'est pas. Mesuré sur vingt interactions
        # simultanées : 1 162 ms en synchronisation complète, 213 ms ici.
        await conn.execute("PRAGMA synchronous = NORMAL")
        # Aucun `PRAGMA journal_mode` ici — cf. `initialiser`. Le CREATE reste :
        # un script ou un test qui écrit sans passer par le démarrage de l'API
        # doit trouver ses tables. `IF NOT EXISTS` en fait un no-op ensuite.
        for instruction in _SCHEMA:
            await conn.execute(instruction)
        # IMMEDIATE : le verrou d'écriture est pris d'entrée, donc l'attente est
        # celle du délai ci-dessus, pas un échec sec.
        yield conn
        await conn.commit()


async def initialiser() -> None:
    """Crée le fichier, fixe le mode de journalisation, crée le schéma.

    Appelée au démarrage de l'API, avant de servir. Le mode WAL doit être fixé
    LÀ et nulle part ailleurs : le changer exige un verrou exclusif, et ce
    changement-là ne respecte PAS le délai d'attente.

    C'est le seul défaut auquel la perte d'écritures simultanées a pu être
    imputée, et il a été isolé : avec le PRAGMA dans le chemin d'écriture, dix
    interactions simultanées perdaient six écritures sur vingt, et un banc
    dédié une sur dix ; sans lui, vingt écritures concurrentes n'en perdent
    aucune sur trois tirages — que la base ait été initialisée ou non.

    WAL sert les lecteurs — /health et l'export ne bloquent plus un écrivain.
    Une base jamais initialisée reste en journal de restauration : elle
    fonctionne, avec des lecteurs qui font attendre les écrivains.
    """
    if not capture_active():
        return
    try:
        chemin = Path(settings.usage_db_path)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(
            chemin, timeout=_VERROU_TIMEOUT_S, isolation_level=None
        ) as conn:
            await conn.execute(f"PRAGMA busy_timeout = {int(_VERROU_TIMEOUT_S * 1000)}")
            await conn.execute("PRAGMA journal_mode = WAL")
            for instruction in _SCHEMA:
                await conn.execute(instruction)
    except Exception as exc:
        _echec("initialiser", exc)


async def record_start(
    *,
    thread_id: str,
    endpoint: str,
    question: str,
    search_query: str | None = None,
    search_translation: str | None = None,
    ranking: Sequence[ChunkResult] = (),
    timings: Mapping[str, Any] | None = None,
) -> None:
    """Ouvre l'enregistrement : la question posée et le classement proposé.

    Un enregistrement couvre deux requêtes HTTP — /chat/start connaît les
    sources PROPOSÉES, /chat/resume celles qui ont été RETENUES — jointes par
    `thread_id`.
    """
    if not capture_active():
        return
    try:
        empreinte, detail = configuration()
        etages = timings or {}
        lignes = [
            (
                thread_id,
                rang,
                chunk.element_id,
                chunk.filename,
                chunk.collection,
                chunk.source_path,
                chunk.section_title,
                chunk.language,
                chunk.page_no,
                chunk.relevance,
                chunk.rerank_score,
            )
            for rang, chunk in enumerate(ranking, start=1)
        ]
        async with _connexion() as conn:
            await conn.execute(
                "INSERT INTO interactions (thread_id, endpoint, started_at, question,"
                " search_query, search_translation, ranked_element_ids, retrieval_ms,"
                " rerank_ms, config_hash, config_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    endpoint,
                    _maintenant(),
                    question,
                    search_query,
                    search_translation,
                    json.dumps([c.element_id for c in ranking], ensure_ascii=False),
                    etages.get("retrieval_ms"),
                    etages.get("rerank_ms"),
                    empreinte,
                    json.dumps(detail, sort_keys=True, ensure_ascii=False),
                ),
            )
            # OR REPLACE plutôt qu'un INSERT nu : `rerank` déduplique par
            # élément, donc la clé tient — mais si elle cessait de tenir, perdre
            # un rang vaut mieux que perdre toute l'interaction.
            await conn.executemany(
                "INSERT OR REPLACE INTO sources_proposees (thread_id, rang, element_id,"
                " filename, collection, source_path, section_title, language, page_no,"
                " relevance, rerank_score, retenue)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                lignes,
            )
    except Exception as exc:
        # Absorption volontaire et large : base verrouillée, disque plein,
        # schéma divergent, ou défaut de ce module. Sans elle, une requête
        # servie deviendrait un 500 à cause d'une observation. Le prix est
        # payé au WARNING et au compteur exposé dans /health, pas au silence.
        _echec("record_start", exc)


async def record_completion(
    *,
    thread_id: str,
    response: str,
    citations: Sequence[Citation] = (),
    images: Sequence[ImageRef] = (),
    search_count: int | None = None,
    submitted: Sequence[SectionContext] = (),
    selected_element_ids: Sequence[str] = (),
    dropped_contexts: int | None = None,
    timings: Mapping[str, Any] | None = None,
) -> None:
    """Complète l'enregistrement : ce qui a été retenu, soumis et répondu.

    `selected_element_ids` est la sélection HUMAINE pour le flux interactif, la
    sélection automatique pour /answer. C'est `endpoint` qui distingue les deux,
    et c'est pourquoi toute lecture des décochages doit filtrer dessus.

    `dropped_contexts` reste NULL quand l'état du graphe ne le porte pas :
    stocker 0 affirmerait qu'aucune source n'a été écartée, ce que personne n'a
    mesuré.
    """
    if not capture_active():
        return
    try:
        etages = timings or {}
        async with _connexion() as conn:
            curseur = await conn.execute(
                # COALESCE sur les trois latences : un dictionnaire de
                # complètement dépourvu d'une clé ne doit pas EFFACER ce que
                # `record_start` avait déjà mesuré. Aujourd'hui les appelants
                # passent le `_metadata` complet, donc le défaut est latent —
                # et silencieux le jour où l'un d'eux ne le passera plus.
                "UPDATE interactions SET completed_at = ?, response = ?, citations = ?,"
                " images = ?, search_count = ?, submitted_element_ids = ?,"
                " submitted_section_ids = ?, dropped_contexts = ?,"
                " retrieval_ms = COALESCE(?, retrieval_ms),"
                " rerank_ms = COALESCE(?, rerank_ms),"
                " generation_ms = COALESCE(?, generation_ms) WHERE thread_id = ?",
                (
                    _maintenant(),
                    response,
                    json.dumps([c.element_id for c in citations], ensure_ascii=False),
                    json.dumps([i.element_id for i in images], ensure_ascii=False),
                    search_count,
                    json.dumps([c.element_id for c in submitted], ensure_ascii=False),
                    json.dumps([c.section_id for c in submitted], ensure_ascii=False),
                    dropped_contexts,
                    etages.get("retrieval_ms"),
                    etages.get("rerank_ms"),
                    etages.get("generation_ms"),
                    thread_id,
                ),
            )
            if curseur.rowcount == 0:
                # L'ouverture a échoué (elle a déjà journalisé) : compléter
                # l'inexistant produirait une interaction sans question ni
                # classement, indiscernable d'une génération directe.
                logger.warning(
                    "Capture d'usage : aucune interaction ouverte pour %s, "
                    "complètement abandonné.",
                    thread_id,
                )
                return
            if selected_element_ids:
                places = ", ".join("?" for _ in selected_element_ids)
                await conn.execute(
                    "UPDATE sources_proposees SET retenue ="
                    f" CASE WHEN element_id IN ({places}) THEN 1 ELSE 0 END"
                    " WHERE thread_id = ?",
                    (*selected_element_ids, thread_id),
                )
    except Exception as exc:
        _echec("record_completion", exc)


async def record_feedback(
    *, thread_id: str, rating: str, comment: str | None = None
) -> Literal["enregistre", "inconnu", "desactive", "echec"]:
    """Attache une appréciation à une interaction déjà enregistrée.

    Retourne le sort de l'écriture plutôt qu'un booléen : l'appelant doit
    distinguer « thread inconnu » (404 légitime) de « capture désactivée » et de
    « échec d'écriture », qui ne sont pas des erreurs du client.
    """
    if not capture_active():
        return "desactive"
    try:
        async with _connexion() as conn:
            curseur = await conn.execute(
                "UPDATE interactions SET rating = ?, rating_comment = ?, rated_at = ?"
                " WHERE thread_id = ?",
                (rating, comment, _maintenant(), thread_id),
            )
            return "enregistre" if curseur.rowcount else "inconnu"
    except Exception as exc:
        _echec("record_feedback", exc)
        return "echec"


async def stats() -> UsageStats:
    """Taille de l'actif : lignes et poids du fichier.

    Aucune purge n'existe — le supprimer serait détruire ce que la capture
    construit. La contrepartie est que la taille doit être VISIBLE : un actif
    qui grossit sans qu'on le sache redevient une fuite.
    """
    chemin = Path(settings.usage_db_path)

    def vide() -> UsageStats:
        # Construit à l'appel, pas d'avance : le compteur d'échecs doit être lu
        # APRÈS l'échec qu'on est en train de signaler, sinon la sonde rend
        # l'ancienne valeur et une base illisible passe pour saine.
        return UsageStats(
            enabled=capture_active(),
            # Le réglage tel qu'il est, pas `str(Path(...))` : `Path("")` vaut
            # `Path(".")`, et la sonde annonçait alors une capture dans le
            # dossier courant là où aucun chemin n'est configuré.
            path=settings.usage_db_path,
            interactions=0,
            sources=0,
            size_bytes=0,
            failures=_echecs,
        )

    # Ne pas créer le fichier pour le mesurer : /health n'écrit pas.
    if not settings.usage_db_path or not chemin.exists():
        return vide()
    try:
        async with aiosqlite.connect(chemin, timeout=_VERROU_TIMEOUT_S) as conn:
            interactions = await _compte(conn, "interactions")
            sources = await _compte(conn, "sources_proposees")
        poids = chemin.stat().st_size
        # Les fichiers -wal et -shm portent les écritures pas encore repliées
        # dans le fichier principal : les omettre sous-évalue l'actif juste
        # après une rafale d'écritures.
        for suffixe in ("-wal", "-shm"):
            annexe = chemin.with_name(chemin.name + suffixe)
            if annexe.exists():
                poids += annexe.stat().st_size
        return UsageStats(
            enabled=capture_active(),
            path=settings.usage_db_path,
            interactions=interactions,
            sources=sources,
            size_bytes=poids,
            failures=_echecs,
        )
    except Exception as exc:
        _echec("stats", exc)
        return vide()


async def _compte(conn: aiosqlite.Connection, table: str) -> int:
    """Nombre de lignes d'une table. `table` est une constante de ce module."""
    async with conn.execute(f"SELECT COUNT(*) FROM {table}") as curseur:
        ligne = await curseur.fetchone()
    return int(ligne[0]) if ligne else 0
