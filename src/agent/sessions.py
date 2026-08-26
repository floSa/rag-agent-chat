"""Registre durable des sessions LangGraph, et purge du checkpointer.

Le checkpointer ne purge rien de lui-même : l'état complet de chaque session —
chunks, embeddings, contextes reconstruits — reste dans `checkpoints.sqlite`
jusqu'à ce que quelqu'un le supprime. Un registre EN MÉMOIRE ne suffit pas à
tenir ce rôle : toute session antérieure au dernier redémarrage lui est
invisible, et ses lignes restent sur le disque indéfiniment. C'était la vraie
croissance non bornée, et corriger l'appel de suppression ne l'aurait pas
touchée.

Le registre vit donc **dans la base du checkpointer elle-même**, en une table à
côté des siennes. Trois raisons, dans cet ordre :

- il survit au redémarrage, donc il atteint une session qu'aucun processus
  vivant n'a jamais vue ;
- il partage exactement la durée de vie de ce qu'il décrit — le fichier effacé
  emporte le registre avec les sessions, et les deux ne peuvent pas dériver ;
- il ne dépend d'aucun réglage étranger. La base de capture d'usage porte
  pourtant `thread_id` et `started_at`, ce qui en ferait un registre tentant :
  elle est désactivable par `USAGE_CAPTURE`, et la purge du checkpointer serait
  alors suspendue par un drapeau qui n'a rien à voir avec elle.

**Ce que la purge ne fait pas, et c'est le point :** elle ne vide pas la base au
démarrage. Le checkpointer est sur disque précisément pour qu'une session en
attente de sélection survive à un redémarrage de l'API — une purge totale au
démarrage détruirait la raison d'être du fichier.

L'horloge est celle du mur (`time.time`) et non `time.monotonic` : c'est la
seule qui survive à un redémarrage. Une horloge qui recule retarde une purge ;
un compteur qui repart à zéro l'annule.
"""

import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.agent.settings import settings

logger = logging.getLogger(__name__)

# Table du registre, dans la base du checkpointer. Le préfixe la distingue des
# tables de la bibliothèque (`checkpoints`, `writes`), qui ne doivent jamais
# entrer en collision avec la nôtre si elle en ajoute une.
_TABLE = "sessions_agent"
_SCHEMA = f"""
    CREATE TABLE IF NOT EXISTS {_TABLE} (
        thread_id  TEXT PRIMARY KEY,
        -- Horodatage mural (epoch). Cf. l'en-tête du module : monotonic ne
        -- survit pas au redémarrage, donc il ne peut pas borner un âge.
        started_at REAL NOT NULL
    )
"""

# Attente avant de renoncer quand une autre connexion tient la base. Le
# checkpointer écrit dans le même fichier ; sans ce délai, deux écritures
# simultanées se soldent par un « database is locked » immédiat.
_VERROU_TIMEOUT_S = 5.0

# Repli quand aucun fichier n'est configuré (CHECKPOINT_DB_PATH vide, donc
# checkpointer en mémoire). Un registre durable serait un mensonge : les
# sessions elles-mêmes ne survivent pas au redémarrage.
_memoire: OrderedDict[str, float] = OrderedDict()

# Compteurs exposés par /health. Le motif `except Exception: logger.debug(...)`
# a caché la panne de cette purge pendant toute la vie du projet : un exploitant
# doit pouvoir lire de l'extérieur combien de sessions ont RÉELLEMENT été
# supprimées, et combien de suppressions ont échoué.
_supprimees = 0
_echecs = 0
_PALIER_RAPPEL = 20
# Dernier décompte lu dans la table du registre. Une sonde /health ne doit pas
# ouvrir la base pour répondre : le nombre est rafraîchi à chaque purge, donc à
# chaque nouvelle session.
_connues = 0


def _echec(operation: str, exc: BaseException) -> None:
    """Journalise un échec de purge — au moins une fois, sans inonder.

    Premier échec en WARNING avec sa trace, puis un rappel tous les
    `_PALIER_RAPPEL` : une base verrouillée échoue à chaque requête, et un
    WARNING par requête noierait le reste du journal.
    """
    global _echecs
    _echecs += 1
    if _echecs == 1 or _echecs % _PALIER_RAPPEL == 0:
        logger.warning(
            "Purge des sessions : %s a échoué (%d échec(s) depuis le démarrage). "
            "L'état de la session reste sur le disque et la purge le retentera.",
            operation,
            _echecs,
            exc_info=exc,
        )


def durable() -> bool:
    """Le registre est-il sur disque ?

    Faux quand `CHECKPOINT_DB_PATH` est vide : le checkpointer est alors en
    mémoire, et le registre l'est aussi.
    """
    return bool(settings.checkpoint_db_path)


def stats() -> tuple[str, int, int, int]:
    """(chemin, sessions connues, sessions supprimées, échecs) pour /health."""
    return (
        settings.checkpoint_db_path or "mémoire",
        len(_memoire) if not durable() else _connues,
        _supprimees,
        _echecs,
    )



def _connexion() -> Any:
    """Connexion à la base du checkpointer, transactions immédiates.

    `isolation_level=None` : sans lui, aiosqlite ouvre une transaction implicite
    qu'il faut valider, et une suppression validée nulle part ne supprime rien.
    """
    chemin = Path(settings.checkpoint_db_path)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    return aiosqlite.connect(chemin, timeout=_VERROU_TIMEOUT_S, isolation_level=None)


async def initialiser(checkpointer: BaseCheckpointSaver[Any]) -> None:
    """Crée la table, adopte les sessions orphelines, purge les périmées.

    Appelée par le `lifespan`, après l'ouverture du checkpointer — la table
    `checkpoints` doit exister pour que l'adoption puisse la lire.

    L'**adoption** est ce qui rend la purge complète : une session écrite avant
    que ce registre n'existe, ou dont la ligne de registre a été perdue, n'est
    référencée que par la table `checkpoints`. Sans adoption elle n'est plus
    atteignable par rien et reste sur le disque pour toujours.

    Son âge réel est inconnu — le checkpointer n'en garde pas la date de
    création lisible sans décoder le msgpack de chaque ligne. Elle est donc
    horodatée à MAINTENANT, ce qui lui accorde un TTL complet. Supprimer à
    l'aveugle détruirait une session en attente de sélection, c'est-à-dire
    exactement ce que le checkpointer sur disque existe pour protéger.
    """
    if not durable():
        logger.info("Registre des sessions en mémoire (CHECKPOINT_DB_PATH vide).")
        return
    try:
        async with _connexion() as conn:
            await conn.execute(f"PRAGMA busy_timeout = {int(_VERROU_TIMEOUT_S * 1000)}")
            await conn.execute(_SCHEMA)
            curseur = await conn.execute(
                f"INSERT OR IGNORE INTO {_TABLE} (thread_id, started_at) "
                f"SELECT DISTINCT thread_id, ? FROM checkpoints",
                (time.time(),),
            )
            adoptees = curseur.rowcount
    except Exception as exc:
        _echec("initialiser", exc)
        return

    if adoptees > 0:
        logger.info(
            "Registre des sessions : %d session(s) du disque adoptée(s), "
            "horodatée(s) à maintenant faute de connaître leur âge.",
            adoptees,
        )
    await purger(checkpointer)


async def enregistrer(thread_id: str) -> None:
    """Inscrit une session au registre, avec sa date de création."""
    maintenant = time.time()
    if not durable():
        _memoire[thread_id] = maintenant
        return
    try:
        async with _connexion() as conn:
            await conn.execute(f"PRAGMA busy_timeout = {int(_VERROU_TIMEOUT_S * 1000)}")
            await conn.execute(_SCHEMA)
            await conn.execute(
                f"INSERT OR REPLACE INTO {_TABLE} (thread_id, started_at) VALUES (?, ?)",
                (thread_id, maintenant),
            )
    except Exception as exc:
        _echec("enregistrer", exc)


def _candidats_memoire(maintenant: float) -> list[str]:
    """Sessions à purger dans le registre en mémoire (âge, puis nombre)."""
    limite = maintenant - settings.session_ttl_seconds
    perimees = [tid for tid, debut in _memoire.items() if debut < limite]
    deja_vues = set(perimees)
    # `_memoire` est ordonné du plus ancien au plus récent : l'excédent est en
    # tête, ce sont les plus vieilles qui sautent.
    vivantes = [tid for tid in _memoire if tid not in deja_vues]
    excedent = vivantes[: max(0, len(vivantes) - settings.max_live_sessions)]
    return perimees + excedent


async def _candidats_disque(conn: Any, maintenant: float) -> list[str]:
    """Sessions à purger dans le registre sur disque (âge, puis nombre)."""
    limite = maintenant - settings.session_ttl_seconds
    async with conn.execute(
        f"SELECT thread_id FROM {_TABLE} WHERE started_at < ?", (limite,)
    ) as curseur:
        perimees = [str(ligne[0]) for ligne in await curseur.fetchall()]
    # Les plus récentes sont gardées ; l'excédent est ce qui suit la borne.
    # `LIMIT -1 OFFSET n` est la façon SQLite de dire « tout sauf les n
    # premiers » — un OFFSET sans LIMIT est un refus de syntaxe.
    async with conn.execute(
        f"SELECT thread_id FROM {_TABLE} WHERE started_at >= ? "
        f"ORDER BY started_at DESC LIMIT -1 OFFSET ?",
        (limite, settings.max_live_sessions),
    ) as curseur:
        excedent = [str(ligne[0]) for ligne in await curseur.fetchall()]
    return perimees + excedent


async def purger(
    checkpointer: BaseCheckpointSaver[Any], epargner: str | None = None
) -> tuple[int, int]:
    """Supprime du checkpointer les sessions périmées par l'âge ou le nombre.

    `epargner` protège la session en cours de création. Elle est inscrite au
    registre AVANT que le graphe ne tourne — pour qu'un `ainvoke` qui écrit ses
    checkpoints puis échoue laisse quand même une session atteignable — donc son
    horodatage est antérieur au « maintenant » de la purge qui suit. Sans cette
    exception, elle est sa propre candidate : la ligne de registre disparaît
    avant que le graphe n'écrive ses checkpoints, et l'état ainsi orphelin ne
    redevient atteignable qu'à l'adoption du prochain démarrage.

    `adelete_thread` et non `delete_thread` : la méthode synchrone
    d'`AsyncSqliteSaver` lève `asyncio.InvalidStateError` (« Synchronous calls
    to AsyncSqliteSaver are only allowed from a different thread ») dès qu'elle
    est appelée depuis le fil de la boucle d'événements — c'est-à-dire depuis
    toute route `async def`. L'exception hérite d'`Exception` : absorbée, elle
    laissait le journal annoncer une purge qui n'avait jamais eu lieu.

    La ligne de registre n'est retirée qu'**après** une suppression réussie. Une
    session dont la suppression échoue reste donc candidate au prochain passage ;
    l'oublier la rendrait définitivement inatteignable, ce qui est le défaut que
    ce registre existe pour fermer.

    Returns:
        (sessions réellement supprimées, échecs de suppression). Ce que la
        fonction rend est ce qui a EU LIEU, pas ce qui a été tenté : le journal
        qui en dérive ne peut plus affirmer une purge qui a échoué.
    """
    global _supprimees, _connues
    maintenant = time.time()

    if not durable():
        candidats = [t for t in _candidats_memoire(maintenant) if t != epargner]
        supprimees = 0
        for tid in candidats:
            try:
                await checkpointer.adelete_thread(tid)
            except Exception as exc:
                _echec(f"adelete_thread({tid})", exc)
                continue
            _memoire.pop(tid, None)
            supprimees += 1
        _supprimees += supprimees
        if candidats:
            logger.info(
                "Purge des sessions : %d supprimée(s) sur %d candidate(s), %d restante(s).",
                supprimees,
                len(candidats),
                len(_memoire),
            )
        return supprimees, len(candidats) - supprimees

    try:
        async with _connexion() as conn:
            await conn.execute(f"PRAGMA busy_timeout = {int(_VERROU_TIMEOUT_S * 1000)}")
            await conn.execute(_SCHEMA)
            candidats = [
                t for t in await _candidats_disque(conn, maintenant) if t != epargner
            ]
            supprimees = 0
            for tid in candidats:
                try:
                    await checkpointer.adelete_thread(tid)
                except Exception as exc:
                    _echec(f"adelete_thread({tid})", exc)
                    continue
                await conn.execute(f"DELETE FROM {_TABLE} WHERE thread_id = ?", (tid,))
                supprimees += 1
            async with conn.execute(f"SELECT count(*) FROM {_TABLE}") as curseur:
                restantes = int((await curseur.fetchone())[0])
    except Exception as exc:
        _echec("purger", exc)
        return 0, 0

    _supprimees += supprimees
    _connues = restantes
    if candidats:
        logger.info(
            "Purge des sessions : %d supprimée(s) sur %d candidate(s), %d restante(s).",
            supprimees,
            len(candidats),
            restantes,
        )
    return supprimees, len(candidats) - supprimees
