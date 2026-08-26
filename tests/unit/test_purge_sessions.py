"""La purge des sessions LangGraph : ce qu'elle supprime, et ce qu'elle annonce.

Cette purge a passé toute la vie du projet à ne rien supprimer pendant que le
journal annonçait le contraire. `_register_thread` appelait `delete_thread`, la
méthode SYNCHRONE d'`AsyncSqliteSaver`, depuis une route `async def` : la
bibliothèque lève `asyncio.InvalidStateError`, un `except Exception:
logger.debug(...)` l'absorbait, et `LOG_LEVEL=INFO` l'effaçait. La ligne
« Sessions purgées : N » suivait quand même.

**Le checkpointer est RÉEL ici, sur un fichier temporaire.** Un faux
checkpointer qui ne lève pas `InvalidStateError` ne prouve rien : c'est
exactement le montage qui a laissé le défaut vivre. Les assertions portent sur
le contenu de `checkpoints.sqlite`, lu en SQL brut — pas sur ce que le code dit
avoir fait.

Seules les frontières du graphe sont neutralisées (recherche, reconstruction,
génération), comme dans `test_flux_interactif.py`.
"""

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.schemas import ChunkResult, SectionContext

QUESTION = "Quelle est la formule de l'écart-type ?"


def _chunk(element_id: str) -> ChunkResult:
    return ChunkResult(
        chunk_id=element_id,
        element_id=element_id,
        graph_node_id=element_id,
        document="Le texte du passage.",
        filename="3. Statistical Toolbox",
        collection="The Statistics Workshop",
        source_path="htms/The Statistics Workshop/3. Statistical Toolbox.html",
        section_title="Dispersion",
        language="en",
        page_no=88,
        label="paragraph",
        distance=0.2,
        rerank_score=3.0,
        relevance=0.95,
    )


def _section(element_id: str) -> SectionContext:
    return SectionContext(
        element_id=element_id,
        section_id="sssssssss1",
        breadcrumbs=[],
        elements=[],
        markdown="Le contexte reconstruit.",
        filename="3. Statistical Toolbox",
        section_title="Dispersion",
    )


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Chemin du fichier de sessions, frontières du graphe neutralisées.

    La capture d'usage est coupée : elle écrirait dans `/app/data`, absent d'une
    machine de test, et son absorption transformerait l'échec en WARNING de
    bruit sans rapport avec ce fichier.
    """
    from src.agent import graph as graph_module
    from src.agent import sessions
    from src.agent.settings import settings

    chemin = tmp_path / "checkpoints.sqlite"
    monkeypatch.setattr(settings, "checkpoint_db_path", str(chemin))
    monkeypatch.setattr(settings, "usage_capture", False)

    monkeypatch.setattr(
        graph_module,
        "retrieve",
        lambda _q, top_k=None, translation=None, chrono=None: [_chunk("abcdef0123")],
    )
    monkeypatch.setattr(graph_module, "rerank", lambda _q, chunks: chunks)
    monkeypatch.setattr(graph_module, "reconstruct_section", _section)

    async def pas_de_reecriture(question, _history):
        return question

    async def pas_de_traduction(_question):
        return None

    async def generation(**_kwargs):
        yield "La dispersion se mesure [src:abcdef0123]."

    monkeypatch.setattr(graph_module, "rewrite_question", pas_de_reecriture)
    monkeypatch.setattr(graph_module, "translate_question", pas_de_traduction)
    monkeypatch.setattr(graph_module, "generate_stream", generation)

    # Compteurs « depuis le démarrage » : chaque test simule un processus neuf,
    # sans quoi ils s'additionnent d'un test à l'autre.
    sessions._memoire.clear()
    sessions._supprimees = 0
    sessions._echecs = 0
    sessions._connues = 0
    return chemin


def _lignes(chemin, thread_id: str) -> int:
    """Lignes de `checkpoints` portant ce thread_id, lues en SQL brut.

    C'est la seule assertion qui vaille : le code peut affirmer ce qu'il veut,
    la table dit ce qui reste. Le fichier -wal n'est pas replié tant que la
    connexion vit, donc la lecture se fait après la fermeture de l'application.
    """
    connexion = sqlite3.connect(chemin)
    try:
        return int(
            connexion.execute(
                "SELECT count(*) FROM checkpoints WHERE thread_id = ?", (thread_id,)
            ).fetchone()[0]
        )
    finally:
        connexion.close()


def _threads(chemin) -> set[str]:
    connexion = sqlite3.connect(chemin)
    try:
        return {
            str(ligne[0])
            for ligne in connexion.execute("SELECT DISTINCT thread_id FROM checkpoints")
        }
    finally:
        connexion.close()


def _redemarrer_le_processus() -> None:
    """Oublie tout registre de sessions vivant en mémoire de processus.

    Un redémarrage de l'API perd ses variables de module. Sans cette remise à
    zéro, un registre EN MÉMOIRE resterait vert — et c'est précisément ce que
    le défaut lui reproche : il n'atteint que ce que le processus courant a
    lui-même créé.
    """
    from src.agent import sessions

    sessions._memoire.clear()


# ─── Ce qui disparaît réellement du disque ────────────────────────────────────

def test_une_session_perimee_disparait_du_fichier_de_sessions(base, monkeypatch) -> None:
    """Le défaut : après deux passages sur une session périmée, sa ligne restait.

    Vérifié en SQL brut sur `checkpoints`, pas sur un compteur du code.
    """
    from src.agent.settings import settings
    from src.api import main

    monkeypatch.setattr(settings, "session_ttl_seconds", 0)

    with TestClient(main.app) as client:
        premier = client.post("/chat/start", json={"question": QUESTION}).json()["thread_id"]
        assert _lignes(base, premier) > 0, "la session doit d'abord exister"
        # Le second start est ce qui déclenche la purge du premier.
        client.post("/chat/start", json={"question": "une autre question"})

    assert _lignes(base, premier) == 0


def test_le_journal_n_annonce_pas_une_purge_qui_a_echoue(base, monkeypatch, caplog) -> None:
    """Le cœur du lot : ce que le journal affirme doit être ce qui a eu lieu.

    La suppression est sabordée. L'assertion ne porte pas sur un libellé — elle
    confronte le nombre ANNONCÉ au nombre RÉELLEMENT supprimé : zéro, puisque la
    ligne est toujours là. Un défaut qui échoue bruyamment se corrige ; un défaut
    qui se déclare résolu ne se corrige jamais.
    """
    from src.agent.settings import settings
    from src.api import main

    monkeypatch.setattr(settings, "session_ttl_seconds", 0)

    with TestClient(main.app) as client:
        premier = client.post("/chat/start", json={"question": QUESTION}).json()["thread_id"]

        async def suppression_impossible(_thread_id: str) -> None:
            raise OSError("disque en lecture seule")

        checkpointer = main.interactive_graph().checkpointer
        monkeypatch.setattr(checkpointer, "adelete_thread", suppression_impossible)

        with caplog.at_level(logging.INFO):
            client.post("/chat/start", json={"question": "une autre question"})

        # Le premier argument de toute ligne de purge est le nombre annoncé.
        annonces = [
            enregistrement.args[0]
            for enregistrement in caplog.records
            if enregistrement.levelno == logging.INFO
            and "purg" in enregistrement.getMessage().lower()
            and enregistrement.args
        ]
        avertissements = [
            enregistrement
            for enregistrement in caplog.records
            if enregistrement.levelno >= logging.WARNING
            and "purge des sessions" in enregistrement.getMessage().lower()
        ]

    assert _lignes(base, premier) > 0, "rien n'a été supprimé, c'est le montage"
    assert annonces, "une purge qui a des candidates doit se journaliser"
    assert all(nombre == 0 for nombre in annonces), (
        f"le journal annonce {annonces} suppression(s) alors qu'aucune n'a eu lieu"
    )
    assert avertissements, "un échec de purge doit se voir, pas seulement en debug"


# ─── La portée : ce qu'aucun processus vivant n'a jamais vu ───────────────────

def test_une_session_anterieure_a_un_redemarrage_est_purgee(base, monkeypatch) -> None:
    """Le vrai défaut de croissance non bornée.

    Un registre en mémoire ne connaît que les sessions créées par le processus
    courant. Toute session antérieure au dernier redémarrage lui est invisible et
    reste sur le disque indéfiniment — corriger l'appel de suppression n'y change
    rien.
    """
    from src.agent.settings import settings
    from src.api import main

    with TestClient(main.app) as client:
        avant = client.post("/chat/start", json={"question": QUESTION}).json()["thread_id"]

    _redemarrer_le_processus()
    # La session date d'avant le redémarrage : à TTL nul, elle est périmée.
    monkeypatch.setattr(settings, "session_ttl_seconds", 0)

    with TestClient(main.app) as client:
        client.post("/chat/start", json={"question": "après redémarrage"})

    assert avant not in _threads(base)


def test_une_session_orpheline_du_registre_est_atteignable(base, monkeypatch) -> None:
    """La forme la plus dure : une session qu'AUCUN registre n'a jamais inscrite.

    C'est le cas de toute session écrite avant que ce registre n'existe. Elle
    n'est référencée que par la table `checkpoints` ; sans adoption au démarrage,
    plus rien ne peut l'atteindre et elle reste sur le disque pour toujours.

    L'adoption l'horodate à MAINTENANT — son âge réel est inconnu — donc elle
    n'est purgée qu'après un TTL complet. C'est délibéré : supprimer à l'aveugle
    détruirait une session en attente de sélection.
    """
    import asyncio

    from src.agent.graph import build_checkpointer, close_checkpointers
    from src.agent.settings import settings
    from src.api import main

    async def poser_une_session_sans_registre() -> None:
        saver = await build_checkpointer()
        config = {"configurable": {"thread_id": "orpheline", "checkpoint_ns": ""}}
        await saver.aput(
            config,
            {
                "v": 1,
                "id": "c1",
                "ts": "2026-08-26T00:00:00+00:00",
                "channel_values": {"question": QUESTION},
                "channel_versions": {},
                "versions_seen": {},
            },
            {"source": "input", "step": 0},
            {},
        )
        await close_checkpointers()

    asyncio.run(poser_une_session_sans_registre())
    assert "orpheline" in _threads(base), "le montage doit d'abord créer l'orpheline"

    _redemarrer_le_processus()
    monkeypatch.setattr(settings, "session_ttl_seconds", 0)

    with TestClient(main.app) as client:
        client.post("/chat/start", json={"question": "après adoption"})

    assert "orpheline" not in _threads(base)


# ─── Non-régression : la raison d'être du checkpointer sur disque ─────────────

def test_une_session_en_attente_de_selection_survit_a_un_redemarrage(base) -> None:
    """Ce que la purge ne doit JAMAIS casser.

    Le checkpointer est sur disque pour cette seule raison : une session
    suspendue avant la sélection des sources doit survivre au redémarrage de
    l'API. Une purge totale au démarrage — la façon la plus simple de borner la
    croissance — détruirait la fonctionnalité pour corriger la fuite.

    Ce test est un garde-fou, pas un détecteur de défaut : il est vert des deux
    côtés du correctif, et c'est ce qu'on lui demande.
    """
    from src.api import main

    with TestClient(main.app) as client:
        thread = client.post("/chat/start", json={"question": QUESTION}).json()["thread_id"]

    _redemarrer_le_processus()

    with TestClient(main.app) as client:
        reponse = client.post(
            "/chat/resume",
            json={"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": False},
        )

    assert reponse.status_code == 200  # noqa: PLR2004
    assert "La dispersion se mesure" in reponse.json()["answer"]


# ─── Ce que /health rend vérifiable de l'extérieur ────────────────────────────

def test_health_publie_les_suppressions_reelles_et_les_echecs(base, monkeypatch) -> None:
    """Un exploitant doit pouvoir vérifier la purge sans lire les logs.

    `purged` compte ce qui a été supprimé, pas ce qui a été tenté : c'est la
    distinction que la ligne de journal d'origine confondait.
    """
    from src.agent.settings import settings
    from src.api import main

    monkeypatch.setattr(settings, "session_ttl_seconds", 0)
    # Les trois sondes de /health attendent leur délai d'expiration sans stores :
    # ce test porte sur le bloc `sessions`, pas sur elles.
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)

    with TestClient(main.app) as client:
        client.post("/chat/start", json={"question": QUESTION})
        client.post("/chat/start", json={"question": "une autre question"})
        etat = client.get("/health").json()["sessions"]

    assert etat["durable"] is True
    assert etat["purged"] == 1
    assert etat["failures"] == 0
