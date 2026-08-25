"""La capture branchée sur l'API : les deux phases, les trois chemins, et la panne.

Le test qui compte le plus est le dernier de chaque paire : **une base
indisponible ne doit pas empêcher de répondre.** La capture est de
l'observation ; la transformer en dépendance dure serait pire que son absence.

Le graphe réel est exécuté, comme dans `test_flux_interactif.py` : seules les
frontières sont neutralisées (recherche, reconstruction, génération).
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.agent import usage
from src.api.schemas import ChunkResult, SectionContext


def _chunk(element_id: str, relevance: float) -> ChunkResult:
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
        relevance=relevance,
    )


_CLASSEMENT = [
    _chunk("abcdef0123", 0.95),
    _chunk("bbbbbbbbbb", 0.81),
    _chunk("cccccccccc", 0.30),
]


# Les deux premiers passages appartiennent à la MÊME section : la reconstruction
# en dédoublonne un. « Ce que l'humain a retenu » et « ce qui a été soumis »
# divergent donc, et c'est cette divergence qui permet de tester qu'on
# n'enregistre pas l'un pour l'autre.
_SECTIONS = {
    "abcdef0123": "ssssssssaa",
    "bbbbbbbbbb": "ssssssssaa",
    "cccccccccc": "ssssssssbb",
}


def _section(element_id: str) -> SectionContext:
    return SectionContext(
        element_id=element_id,
        section_id=_SECTIONS.get(element_id, "ssssssssxx"),
        breadcrumbs=[],
        elements=[],
        markdown="Le contexte reconstruit.",
        filename="3. Statistical Toolbox",
        section_title="Dispersion",
    )


def _client(tmp_path, monkeypatch, capture: bool):
    from src.agent import graph as graph_module
    from src.api import main

    monkeypatch.setattr(main.settings, "checkpoint_db_path", "")
    # Les sondes de /health sont neutralisées : sans cela, chaque appel attend
    # ChromaDB et NebulaGraph, absents en CI comme ici.
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    # Adresse qui refuse immédiatement, plutôt qu'un nom qui attend sa résolution.
    monkeypatch.setattr(main.settings, "ollama_host", "http://127.0.0.1:1")
    monkeypatch.setattr(usage.settings, "usage_db_path", str(tmp_path / "usage.sqlite"))
    monkeypatch.setattr(usage.settings, "usage_capture", capture)
    monkeypatch.setattr(usage, "_echecs", 0)

    monkeypatch.setattr(
        graph_module, "retrieve", lambda _q, top_k=None, translation=None: list(_CLASSEMENT)
    )
    monkeypatch.setattr(graph_module, "rerank", lambda _q, chunks: chunks)
    monkeypatch.setattr(graph_module, "reconstruct_section", _section)
    monkeypatch.setattr(main, "reconstruct_section", _section)

    async def pas_de_reecriture(question, _history):
        return f"{question} (autonome)"

    async def pas_de_traduction(_question):
        return "how to measure dispersion"

    async def generation(*_args, **_kwargs):
        for token in ("La dispersion ", "se mesure [src:abcdef0123]."):
            yield token

    monkeypatch.setattr(graph_module, "rewrite_question", pas_de_reecriture)
    monkeypatch.setattr(graph_module, "translate_question", pas_de_traduction)
    monkeypatch.setattr(graph_module, "generate_stream", generation)
    monkeypatch.setattr(main, "generate_stream", generation)

    return TestClient(main.app)


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Le gestionnaire de contexte est obligatoire : sans lui le lifespan ne
    # s'exécute pas, le graphe n'est pas compilé et les routes rendent 503.
    with _client(tmp_path, monkeypatch, capture=True) as testclient:
        yield testclient


@pytest.fixture
def client_sans_capture(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, capture=False) as testclient:
        yield testclient


@pytest.fixture
def base(tmp_path):
    return tmp_path / "usage.sqlite"


def _lire(chemin, requete, *params):
    with sqlite3.connect(chemin) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(ligne) for ligne in conn.execute(requete, params)]


def _flux(client, chemin, corps):
    with client.stream("POST", chemin, json=corps) as flux:
        return [
            json.loads(ligne[len("data:"):].strip())
            for ligne in flux.iter_lines()
            if ligne.startswith("data:")
        ]


# ─── Le flux interactif, les deux phases ──────────────────────────────────────

def test_start_et_resume_forment_un_seul_enregistrement(client, base) -> None:
    """Deux requêtes HTTP, un enregistrement, joint par thread_id."""
    demarrage = client.post(
        "/chat/start", json={"question": "Comment mesurer la dispersion ?"}
    ).json()
    thread = demarrage["thread_id"]

    ouvert = _lire(base, "SELECT * FROM interactions WHERE thread_id = ?", thread)
    assert len(ouvert) == 1
    assert ouvert[0]["endpoint"] == "chat"
    assert ouvert[0]["question"] == "Comment mesurer la dispersion ?"
    assert ouvert[0]["search_query"] == "Comment mesurer la dispersion ? (autonome)"
    assert ouvert[0]["search_translation"] == "how to measure dispersion"
    assert ouvert[0]["completed_at"] is None
    assert json.loads(ouvert[0]["ranked_element_ids"]) == [c.element_id for c in _CLASSEMENT]

    evenements = _flux(
        client,
        "/chat/resume",
        {"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": True},
    )
    assert [e for e in evenements if e.get("done")], "la réponse doit être servie"

    complet = _lire(base, "SELECT * FROM interactions WHERE thread_id = ?", thread)[0]
    assert complet["completed_at"] is not None
    assert "La dispersion se mesure" in complet["response"]
    assert json.loads(complet["citations"]) == ["abcdef0123"]
    assert json.loads(complet["submitted_section_ids"]) == ["ssssssssaa"]
    assert complet["generation_ms"] is not None
    assert complet["config_hash"]
    # Personne n'a mesuré de source écartée sur ce chemin : NULL, pas 0.
    assert complet["dropped_contexts"] is None


def test_le_decochage_est_derivable_apres_le_flux_complet(client, base) -> None:
    """Le gros lot du dispositif : une source bien classée, écartée par un humain.

    C'est l'annotation négative qu'aucun jeu doré généré ne contient.
    """
    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]
    _flux(
        client,
        "/chat/resume",
        {"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": True},
    )

    sorts = _lire(
        base,
        "SELECT s.rang, s.element_id, s.relevance, s.retenue FROM sources_proposees s"
        " JOIN interactions i USING (thread_id) WHERE i.endpoint = 'chat' ORDER BY s.rang",
    )

    assert [(x["rang"], x["retenue"]) for x in sorts] == [(1, 1), (2, 0), (3, 0)]
    ecartee = next(x for x in sorts if x["rang"] == 2)  # noqa: PLR2004
    assert ecartee["relevance"] == pytest.approx(0.81)


def test_une_selection_abandonnee_ne_compte_pas_comme_un_decochage(client, base) -> None:
    """L'utilisateur ferme l'onglet devant l'écran de sélection : rien n'est décoché."""
    client.post("/chat/start", json={"question": "q"})

    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees WHERE retenue IS NULL")[0][
        "n"
    ] == 3  # noqa: PLR2004
    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees WHERE retenue = 0")[0]["n"] == 0


def test_la_retenue_suit_la_selection_humaine_et_non_les_sections_soumises(
    client, base
) -> None:
    """Deux notions distinctes, qu'un enregistrement ne doit pas confondre.

    Les deux premiers passages sont dans la même section : la reconstruction n'en
    soumet qu'une. Enregistrer « ce qui a été soumis » à la place de « ce que
    l'humain a coché » ferait passer le second pour décoché — une annotation
    négative inventée. La boucle agentique produit le symétrique : des sources
    soumises que personne n'a jamais vues.
    """
    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]
    _flux(
        client,
        "/chat/resume",
        {
            "thread_id": thread,
            "selected_element_ids": ["abcdef0123", "bbbbbbbbbb"],
            "stream": True,
        },
    )

    sorts = _lire(
        base, "SELECT rang, retenue FROM sources_proposees ORDER BY rang"
    )
    soumises = json.loads(
        _lire(base, "SELECT submitted_section_ids FROM interactions")[0][
            "submitted_section_ids"
        ]
    )

    assert [(x["rang"], x["retenue"]) for x in sorts] == [(1, 1), (2, 1), (3, 0)]
    assert soumises == ["ssssssssaa"], "une seule section pour deux passages retenus"


def test_l_ecriture_suit_la_generation_au_lieu_de_la_preceder(
    client, base, monkeypatch
) -> None:
    """La contrainte du lot : rien de synchrone dans le chemin de diffusion.

    L'ordre est observé depuis l'intérieur de l'application — un espion sur
    l'écriture et un compteur de tokens — parce que le client de test tamponne
    la réponse SSE et ne peut donc pas l'observer de l'extérieur. La position
    exacte de l'écriture (après le dernier événement plutôt qu'avant) tient au
    point d'appel, que ce test ne distingue pas ; ce qu'il interdit, c'est
    d'écrire avant d'avoir répondu.
    """
    from src.agent import graph as graph_module
    from src.api import main

    journal: list[str] = []

    async def generation(*_args, **_kwargs):
        for token in ("La dispersion ", "se mesure [src:abcdef0123]."):
            journal.append("token")
            yield token

    ecriture_reelle = main.record_completion

    async def espion(**kwargs):
        journal.append("ecriture")
        await ecriture_reelle(**kwargs)

    monkeypatch.setattr(graph_module, "generate_stream", generation)
    monkeypatch.setattr(main, "record_completion", espion)

    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]
    _flux(
        client,
        "/chat/resume",
        {"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": True},
    )

    assert journal == ["token", "token", "ecriture"]
    assert _lire(base, "SELECT completed_at FROM interactions WHERE thread_id = ?", thread)[0][
        "completed_at"
    ] is not None


# ─── Les deux autres chemins ──────────────────────────────────────────────────

def test_answer_est_capture_avec_son_classement_et_ses_latences(client, base) -> None:
    """Le chemin d'évaluation, distingué par `endpoint` : aucune décision humaine."""
    reponse = client.post("/answer", json={"question": "Comment mesurer la dispersion ?"})
    assert reponse.status_code == 200  # noqa: PLR2004

    ligne = _lire(base, "SELECT * FROM interactions WHERE endpoint = 'answer'")[0]
    assert ligne["completed_at"] is not None
    assert json.loads(ligne["ranked_element_ids"]) == [c.element_id for c in _CLASSEMENT]
    # Ici le nombre de sources écartées est calculé par l'endpoint : c'est un
    # chiffre, pas un NULL.
    assert ligne["dropped_contexts"] == 0
    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees")[0]["n"] == 3  # noqa: PLR2004


def test_chat_simple_est_capture_sans_source_proposee(client, base) -> None:
    """Le client arrive avec ses sources : rien ne lui a été proposé.

    Écrire ses element_ids comme « retenus » gonflerait le taux de retenue d'une
    décision que personne n'a prise. La question, elle, est la donnée utile.
    """
    evenements = _flux(
        client,
        "/chat/simple",
        {"question": "Et pour les femmes ?", "selected_element_ids": ["abcdef0123"]},
    )
    assert [e for e in evenements if e.get("done")]

    ligne = _lire(base, "SELECT * FROM interactions WHERE endpoint = 'chat_simple'")[0]
    assert ligne["question"] == "Et pour les femmes ?"
    assert "La dispersion se mesure" in ligne["response"]
    assert json.loads(ligne["submitted_element_ids"]) == ["abcdef0123"]
    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees")[0]["n"] == 0


# ─── La panne ─────────────────────────────────────────────────────────────────

def test_une_base_en_echec_ne_casse_ni_start_ni_resume(client, base, monkeypatch) -> None:
    """La garantie centrale du lot, vérifiée là où elle compte : dans l'API.

    Sans elle, un disque plein transformerait un service qui répond en service
    qui rend 500.
    """
    def connexion_en_echec(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(usage.aiosqlite, "connect", connexion_en_echec)

    demarrage = client.post("/chat/start", json={"question": "q"})
    assert demarrage.status_code == 200  # noqa: PLR2004
    groupes = demarrage.json()["groups"]
    assert len(groupes[0]["chunks"]) == 3, "les sources sont servies normalement"  # noqa: PLR2004

    evenements = _flux(
        client,
        "/chat/resume",
        {
            "thread_id": demarrage.json()["thread_id"],
            "selected_element_ids": ["abcdef0123"],
            "stream": True,
        },
    )
    final = [e for e in evenements if e.get("done")][-1]

    assert "La dispersion se mesure" in final["answer"]
    assert final["citations"][0]["filename"] == "3. Statistical Toolbox"
    assert usage._echecs >= 2, "les échecs sont comptés, pas ignorés"  # noqa: SLF001, PLR2004
    assert _lire(base, "SELECT COUNT(*) n FROM interactions")[0]["n"] == 0


def test_une_base_inaccessible_ne_casse_pas_answer(client, tmp_path, monkeypatch) -> None:
    """Volume non monté : le chemin de capture est occupé par un fichier."""
    obstacle = tmp_path / "occupe"
    obstacle.write_text("je ne suis pas un dossier", encoding="utf-8")
    monkeypatch.setattr(usage.settings, "usage_db_path", str(obstacle / "usage.sqlite"))

    reponse = client.post("/answer", json={"question": "q"})

    assert reponse.status_code == 200  # noqa: PLR2004
    assert reponse.json()["answer"]
    assert usage._echecs >= 1  # noqa: SLF001


def test_capture_desactivee_laisse_l_api_intacte_et_le_disque_vide(
    client_sans_capture, base
) -> None:
    """Le drapeau est coupé AVANT le démarrage, comme en production.

    Le couper après aurait laissé le démarrage créer la base, et le test aurait
    mesuré l'ordre des fixtures au lieu du drapeau.
    """
    client = client_sans_capture
    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]
    evenements = _flux(
        client,
        "/chat/resume",
        {"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": True},
    )

    assert [e for e in evenements if e.get("done")]
    assert not base.exists(), "un fichier vide ferait croire à une capture en cours"
    assert usage._echecs == 0, "rien n'a été tenté, donc rien n'a échoué"  # noqa: SLF001


# ─── L'appréciation ───────────────────────────────────────────────────────────

def test_feedback_attache_une_note_a_l_interaction(client, base) -> None:
    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]
    _flux(
        client,
        "/chat/resume",
        {"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": True},
    )

    reponse = client.post(
        "/feedback",
        json={"thread_id": thread, "rating": "inutile", "comment": "Répond à côté."},
    )

    assert reponse.status_code == 200  # noqa: PLR2004
    assert reponse.json()["recorded"] is True
    ligne = _lire(base, "SELECT rating, rating_comment FROM interactions WHERE thread_id = ?",
                  thread)[0]
    assert (ligne["rating"], ligne["rating_comment"]) == ("inutile", "Répond à côté.")


def test_feedback_sur_un_thread_inconnu_repond_404_et_pas_500(client) -> None:
    """Un identifiant inventé ou périmé est une erreur du client, pas une panne.

    Le distinguer d'un échec d'écriture est tout l'intérêt de faire remonter le
    sort de l'écriture plutôt qu'un booléen.
    """
    reponse = client.post("/feedback", json={"thread_id": "jamais-vu", "rating": "utile"})

    assert reponse.status_code == 404  # noqa: PLR2004
    assert "thread_id" in reponse.json()["detail"]


def test_feedback_avec_capture_desactivee_ne_blame_pas_le_client(
    client_sans_capture,
) -> None:
    """200 avec `recorded: false` : ce n'est pas au client d'en porter la faute."""
    reponse = client_sans_capture.post(
        "/feedback", json={"thread_id": "peu-importe", "rating": "utile"}
    )

    assert reponse.status_code == 200  # noqa: PLR2004
    assert reponse.json() == {"recorded": False, "detail": "Capture d'usage désactivée."}


def test_une_note_hors_du_binaire_est_refusee_par_le_schema(client) -> None:
    """Le rating est binaire par conception : une échelle ne se remplit pas, et
    « 3/5 » ne se lit pas. Le schéma doit l'imposer, sinon la colonne finit par
    contenir n'importe quoi et les comptages ne veulent plus rien dire."""
    assert client.post(
        "/feedback", json={"thread_id": "t", "rating": "moyen"}
    ).status_code == 422  # noqa: PLR2004


# ─── La taille, visible ───────────────────────────────────────────────────────

def test_health_expose_la_taille_de_l_actif(client, base) -> None:
    """Aucune purge n'existe : la taille doit être visible, sinon l'actif
    redevient une fuite. C'est la contrepartie assumée du « pas de purge »."""
    avant = client.get("/health").json()["usage"]
    assert avant["enabled"] is True
    assert avant["interactions"] == 0
    assert avant["failures"] == 0

    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]
    _flux(
        client,
        "/chat/resume",
        {"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": True},
    )

    apres = client.get("/health").json()["usage"]
    assert apres["interactions"] == 1
    assert apres["sources"] == 3  # noqa: PLR2004
    assert apres["size_bytes"] > 0
    assert apres["path"] == str(base)


def test_health_survit_a_une_base_de_capture_illisible(client, monkeypatch) -> None:
    """Une sonde qui tombe parce qu'une base d'OBSERVATION est illisible serait
    une régression, pas une mesure. Le compteur d'échecs dit ce qui s'est passé."""
    def lecture_en_echec(*_args, **_kwargs):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(usage.aiosqlite, "connect", lecture_en_echec)

    reponse = client.get("/health")

    assert reponse.status_code == 200  # noqa: PLR2004
    assert reponse.json()["usage"]["failures"] >= 1


def test_health_ne_ment_pas_quand_la_capture_est_coupee(client_sans_capture) -> None:
    etat = client_sans_capture.get("/health").json()["usage"]

    assert etat["enabled"] is False
    assert etat["size_bytes"] == 0
