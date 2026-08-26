"""Capture d'usage : le module, sa résilience, et ce qu'il rend interrogeable.

Ces tests portent sur `src/agent/usage.py` seul — la base réelle est ouverte,
dans un dossier temporaire. Le branchement sur l'API est couvert par
`test_capture_branchement.py`.

Le point le plus important n'est pas qu'on sache écrire : c'est qu'un échec
d'écriture ne remonte JAMAIS à l'appelant. La capture est de l'observation, pas
une fonctionnalité.
"""

import asyncio
import json
import logging
import os
import pathlib
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from src.agent import usage
from src.api.schemas import Citation, ImageRef, SectionContext


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base d'usage neuve, capture active, compteur d'échecs remis à zéro."""
    chemin = tmp_path / "usage.sqlite"
    monkeypatch.setattr(usage.settings, "usage_db_path", str(chemin))
    monkeypatch.setattr(usage.settings, "usage_capture", True)
    monkeypatch.setattr(usage, "_echecs", 0)
    return chemin


def _lire(chemin, requete, *params):
    with sqlite3.connect(chemin) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(ligne) for ligne in conn.execute(requete, params)]


def _chunk(element_id, rang_relevance, **extra):
    from src.api.schemas import ChunkResult

    defauts = dict(
        chunk_id=f"{element_id}_part0",
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
        relevance=rang_relevance,
    )
    defauts.update(extra)
    return ChunkResult(**defauts)


def _section(element_id, section_id="sssssssss1"):
    return SectionContext(
        element_id=element_id,
        section_id=section_id,
        breadcrumbs=[],
        elements=[],
        markdown="Le contexte reconstruit.",
        filename="3. Statistical Toolbox",
        section_title="Dispersion",
    )


# ─── L'empreinte de configuration ─────────────────────────────────────────────

def test_l_empreinte_suit_le_contenu_des_prompts(tmp_path, monkeypatch) -> None:
    """Une modification de prompt doit changer l'empreinte, et elle seule.

    Sans ce condensat, une modification de prompt n'est attribuable dans aucun
    enregistrement : deux réponses différentes portent la même configuration
    apparente, et l'on croit avoir mesuré un effet de réglage.
    """
    dossier = tmp_path / "prompts"
    dossier.mkdir()
    (dossier / "system.txt").write_text("Tu réponds à partir des sources.", encoding="utf-8")
    monkeypatch.setattr(usage.settings, "prompts_dir", str(dossier))

    avant, detail_avant = usage.configuration()
    stable, _ = usage.configuration()
    (dossier / "system.txt").write_text("Tu réponds en citant tout.", encoding="utf-8")
    apres, detail_apres = usage.configuration()

    assert stable == avant, "à configuration identique, l'empreinte doit grouper"
    assert apres != avant
    assert detail_apres["prompts_sha256"] != detail_avant["prompts_sha256"]
    # Le reste de la configuration n'a pas bougé : c'est bien le prompt qui parle.
    assert {k: v for k, v in detail_apres.items() if k != "prompts_sha256"} == {
        k: v for k, v in detail_avant.items() if k != "prompts_sha256"
    }


def test_l_empreinte_voit_un_gabarit_range_dans_un_sous_dossier(tmp_path, monkeypatch) -> None:
    """`prompts/` est plat aujourd'hui. Le jour où il ne l'est plus, l'empreinte
    ne doit pas affirmer « prompt inchangé » sur un prompt modifié."""
    dossier = tmp_path / "prompts"
    (dossier / "partiels").mkdir(parents=True)
    (dossier / "system.txt").write_text("Tu réponds.", encoding="utf-8")
    monkeypatch.setattr(usage.settings, "prompts_dir", str(dossier))

    avant = usage._condensat_prompts()  # noqa: SLF001
    (dossier / "partiels" / "citations.j2").write_text("{{ ctx }}", encoding="utf-8")
    ajoute = usage._condensat_prompts()  # noqa: SLF001
    (dossier / "partiels" / "citations.j2").write_text("{{ autre }}", encoding="utf-8")
    modifie = usage._condensat_prompts()  # noqa: SLF001

    assert ajoute != avant, "un gabarit ajouté en sous-dossier doit compter"
    assert modifie != ajoute, "et sa modification aussi"


def test_l_empreinte_suit_les_reglages_de_recherche(tmp_path, monkeypatch) -> None:
    dossier = tmp_path / "prompts"
    dossier.mkdir()
    (dossier / "system.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(usage.settings, "prompts_dir", str(dossier))

    avant, _ = usage.configuration()
    monkeypatch.setattr(usage.settings, "retrieval_top_k", 20)
    apres, detail = usage.configuration()

    assert apres != avant
    assert detail["retrieval_top_k"] == 20  # noqa: PLR2004


# ─── Le drapeau ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_capture_desactivee_n_ecrit_rien_et_ne_cree_pas_le_fichier(base, monkeypatch) -> None:
    """USAGE_CAPTURE=false doit être un vrai interrupteur, pas un filtre en aval.

    Créer un fichier vide suffirait à faire croire à une capture en cours, et à
    faire échouer la promesse tenue dans SECURITY.md.
    """
    monkeypatch.setattr(usage.settings, "usage_capture", False)

    await usage.record_start(
        thread_id="t1", endpoint="chat", question="q", ranking=[_chunk("aaaaaaaaa1", 0.9)]
    )
    await usage.record_completion(thread_id="t1", response="r")
    resultat = await usage.record_feedback(thread_id="t1", rating="utile")

    assert not base.exists()
    assert resultat == "desactive"
    assert not usage.capture_active()


# ─── Les deux phases, jointes par thread_id ───────────────────────────────────

@pytest.mark.asyncio
async def test_l_enregistrement_couvre_les_deux_phases_jointes_par_thread_id(base) -> None:
    """Un enregistrement naît au start et se complète au resume.

    C'est la forme imposée par le flux : /chat/start connaît les sources
    PROPOSÉES, /chat/resume celles qui ont été RETENUES et la réponse.
    """
    ranking = [_chunk("aaaaaaaaa1", 0.91), _chunk("aaaaaaaaa2", 0.81), _chunk("aaaaaaaaa3", 0.4)]

    await usage.record_start(
        thread_id="t-2phases",
        endpoint="chat",
        question="Comment mesurer la dispersion ?",
        search_query="mesure de la dispersion statistique",
        search_translation="how to measure dispersion",
        ranking=ranking,
        timings={"retrieval_ms": 120, "rerank_ms": 340},
    )

    ouverture = _lire(base, "SELECT * FROM interactions")[0]
    assert ouverture["question"] == "Comment mesurer la dispersion ?"
    assert ouverture["search_translation"] == "how to measure dispersion"
    assert json.loads(ouverture["ranked_element_ids"]) == [c.element_id for c in ranking]
    assert ouverture["completed_at"] is None
    assert ouverture["config_hash"]

    await usage.record_completion(
        thread_id="t-2phases",
        response="La dispersion se mesure [src:aaaaaaaaa1].",
        citations=[
            Citation(
                element_id="aaaaaaaaa1", filename="3. Statistical Toolbox",
                page_no=88, text_excerpt="…",
            )
        ],
        images=[ImageRef(element_id="aaaaaaaaa9", minio_url="/media/x.png")],
        search_count=1,
        submitted=[_section("aaaaaaaaa1"), _section("aaaaaaaaa2", "sssssssss2")],
        selected_element_ids=["aaaaaaaaa1", "aaaaaaaaa2"],
        dropped_contexts=1,
        timings={"retrieval_ms": 120, "rerank_ms": 340, "generation_ms": 8400},
    )

    lignes = _lire(base, "SELECT * FROM interactions")
    assert len(lignes) == 1, "les deux phases sont un seul enregistrement"
    complet = lignes[0]
    # La VALEUR de l'horodatage, pas seulement sa présence : un « maintenant »
    # cassé — chaîne vide, heure locale, format non trié — rendrait tout
    # classement chronologique faux sans qu'aucune assertion ne bouge.
    acheve = datetime.fromisoformat(complet["completed_at"])
    assert acheve.tzinfo == UTC, "un horodatage sans fuseau ne se compare pas"
    assert complet["completed_at"] >= ouverture["started_at"], (
        "l'ordre ISO 8601 en UTC est l'ordre chronologique : c'est ce qui rend "
        "ORDER BY started_at juste, et --since utilisable"
    )
    assert complet["response"].startswith("La dispersion")
    assert json.loads(complet["citations"]) == ["aaaaaaaaa1"]
    assert json.loads(complet["images"]) == ["aaaaaaaaa9"]
    assert json.loads(complet["submitted_element_ids"]) == ["aaaaaaaaa1", "aaaaaaaaa2"]
    assert json.loads(complet["submitted_section_ids"]) == ["sssssssss1", "sssssssss2"]
    assert complet["dropped_contexts"] == 1
    assert complet["search_count"] == 1
    assert (complet["retrieval_ms"], complet["rerank_ms"], complet["generation_ms"]) == (
        120, 340, 8400,
    )

    # La ligne de source ENTIÈRE, comparée d'un bloc. Colonne par colonne, sept
    # d'entre elles n'étaient gardées par rien : `rerank_score`, `page_no`,
    # `language`, `collection`, `source_path` pouvaient cesser d'être écrites
    # sans qu'un test bronche. Deux de ces sept cassent une requête documentée
    # si elles régressent — `collection` et `source_path` portent le GROUP BY de
    # la requête des décochages, qui s'effondrerait sur une seule ligne.
    assert _lire(base, "SELECT * FROM sources_proposees WHERE rang = 1")[0] == {
        "thread_id": "t-2phases",
        "rang": 1,
        "element_id": "aaaaaaaaa1",
        "filename": "3. Statistical Toolbox",
        "collection": "The Statistics Workshop",
        "source_path": "htms/The Statistics Workshop/3. Statistical Toolbox.html",
        "section_title": "Dispersion",
        "language": "en",
        "page_no": 88,
        "relevance": 0.91,
        "rerank_score": 3.0,
        "retenue": 1,
    }


@pytest.mark.asyncio
async def test_le_completement_n_efface_pas_les_latences_deja_mesurees(base) -> None:
    """Un complètement sans latences de recherche ne doit rien effacer.

    `record_start` mesure la recherche et le reranking ; le complètement
    repassait ces deux colonnes par `etages.get(...)`, donc un dictionnaire qui
    ne les porte pas les remettait à NULL. Latent tant que les appelants
    passent le `_metadata` complet — et muet le jour où l'un d'eux ne le passe
    plus, puisque la donnée perdue est une donnée qu'on ne cherchait pas.
    """
    await usage.record_start(
        thread_id="t-latences", endpoint="chat", question="q",
        timings={"retrieval_ms": 480, "rerank_ms": 340},
    )
    await usage.record_completion(
        thread_id="t-latences", response="r", timings={"generation_ms": 8400}
    )

    ligne = _lire(base, "SELECT retrieval_ms, rerank_ms, generation_ms FROM interactions")[0]

    assert (ligne["retrieval_ms"], ligne["rerank_ms"]) == (480, 340)
    assert ligne["generation_ms"] == 8400  # noqa: PLR2004


@pytest.mark.asyncio
async def test_dropped_contexts_inconnu_reste_null(base) -> None:
    """NULL, jamais 0 : 0 affirmerait qu'aucune source n'a été écartée."""
    await usage.record_start(thread_id="t-null", endpoint="chat", question="q")
    await usage.record_completion(thread_id="t-null", response="r")

    assert _lire(base, "SELECT dropped_contexts FROM interactions")[0][
        "dropped_contexts"
    ] is None


# ─── Le décochage ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_decochage_se_lit_avec_son_rang_et_sa_pertinence(base) -> None:
    """L'annotation négative que le lot existe pour récolter.

    Une source classée deuxième à 0,81 puis décochée doit se lire comme telle,
    en SQL, sans script d'analyse.
    """
    await usage.record_start(
        thread_id="t-decoche",
        endpoint="chat",
        question="q",
        ranking=[
            _chunk("aaaaaaaaa1", 0.91),
            _chunk("aaaaaaaaa2", 0.81, section_title="Corrélation"),
            _chunk("aaaaaaaaa3", 0.40),
        ],
    )
    await usage.record_completion(
        thread_id="t-decoche",
        response="r",
        selected_element_ids=["aaaaaaaaa1", "aaaaaaaaa3"],
    )

    ecartees = _lire(
        base,
        "SELECT rang, element_id, relevance, section_title FROM sources_proposees"
        " WHERE retenue = 0 ORDER BY rang",
    )

    assert [ligne["element_id"] for ligne in ecartees] == ["aaaaaaaaa2"]
    assert ecartees[0]["rang"] == 2  # noqa: PLR2004
    assert ecartees[0]["relevance"] == pytest.approx(0.81)
    assert ecartees[0]["section_title"] == "Corrélation"


@pytest.mark.asyncio
async def test_la_vue_decochages_ecarte_les_zeros_automatiques_de_answer(base) -> None:
    """Le filtre sur `endpoint` cesse d'être une convention.

    /answer retient `AUTO_SELECT_TOP_K` sources et écrit `retenue = 0` sur
    toutes les autres : trois faux décochages par question, près de mille par
    campagne de 138 questions, indiscernables en SQL d'un décochage humain. La
    documentation disait « toute lecture DOIT filtrer sur endpoint » — une
    convention ne survit pas à une requête écrite de mémoire dans six mois.

    Le montage est celui du critère d'acceptation : une interaction interactive
    qui produit trois décochages humains, une interaction /answer qui produit
    trois zéros automatiques.
    """
    await usage.record_start(
        thread_id="t-humain", endpoint="chat", question="question réellement posée",
        ranking=[_chunk(f"hhhhhhhhh{n}", 0.9 - n / 10) for n in range(4)],
    )
    await usage.record_completion(
        thread_id="t-humain", response="r", selected_element_ids=["hhhhhhhhh0"]
    )
    await usage.record_start(
        thread_id="t-campagne", endpoint="answer", question="question de campagne",
        ranking=[_chunk(f"ccccccccc{n}", 0.9 - n / 10) for n in range(6)],
    )
    await usage.record_completion(
        thread_id="t-campagne", response="r",
        selected_element_ids=[f"ccccccccc{n}" for n in range(3)],
    )

    brut = _lire(base, "SELECT COUNT(*) n FROM sources_proposees WHERE retenue = 0")[0]["n"]
    par_la_vue = _lire(base, "SELECT COUNT(*) n FROM decochages")[0]["n"]

    assert brut == 6, "la table brute mélange les deux, c'est le piège"  # noqa: PLR2004
    assert par_la_vue == 3, "la vue ne doit rendre que les décochages humains"  # noqa: PLR2004
    assert {ligne["element_id"] for ligne in _lire(base, "SELECT element_id FROM decochages")} == {
        "hhhhhhhhh1", "hhhhhhhhh2", "hhhhhhhhh3",
    }
    # La vue porte la question, pour qu'un décochage se lise sans jointure.
    assert _lire(base, "SELECT DISTINCT question FROM decochages")[0]["question"] == (
        "question réellement posée"
    )
    # `sources_humaines` garde les trois états : c'est elle que lit le taux de
    # retenue par rang, qui a besoin des retenues autant que des écartées.
    assert _lire(base, "SELECT COUNT(*) n FROM sources_humaines")[0]["n"] == 4  # noqa: PLR2004


@pytest.mark.asyncio
async def test_une_selection_jamais_faite_reste_indeterminee(base) -> None:
    """Abandonner devant l'écran de sélection n'est pas décocher.

    Compter un abandon comme un décochage fabriquerait une annotation négative
    que personne n'a produite — c'est-à-dire exactement le biais que le jeu
    doré généré a déjà.
    """
    await usage.record_start(
        thread_id="t-abandon", endpoint="chat", question="q",
        ranking=[_chunk("aaaaaaaaa1", 0.9)],
    )

    assert _lire(base, "SELECT retenue FROM sources_proposees")[0]["retenue"] is None
    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees WHERE retenue = 0")[0]["n"] == 0


# ─── Un échec de capture ne remonte jamais ────────────────────────────────────

@pytest.mark.asyncio
async def test_un_echec_d_ecriture_est_absorbe_et_journalise_en_warning(
    base, monkeypatch, caplog
) -> None:
    """Base verrouillée, disque plein, schéma divergent : on journalise, on sert.

    Le motif `except Exception: logger.debug(...)` du dépôt a déjà caché un
    défaut pendant tout un lot : le premier échec doit sortir en WARNING.
    """
    def connexion_en_echec(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(usage.aiosqlite, "connect", connexion_en_echec)

    with caplog.at_level(logging.WARNING, logger="src.agent.usage"):
        await usage.record_start(thread_id="t-echec", endpoint="chat", question="q")
        await usage.record_completion(thread_id="t-echec", response="r")

    assert usage._echecs == 2, "chaque échec est compté, pour être exposé dans /health"  # noqa: SLF001, PLR2004
    warnings = [e for e in caplog.records if e.levelno == logging.WARNING]
    assert warnings, "un échec silencieux est ce qui a déjà coûté un lot entier"
    assert "record_start" in warnings[0].message
    assert (await usage.stats()).failures == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_une_base_inaccessible_est_absorbee(tmp_path, monkeypatch) -> None:
    """Volume non monté, chemin occupé par un fichier : même traitement."""
    obstacle = tmp_path / "data"
    obstacle.write_text("je ne suis pas un dossier", encoding="utf-8")
    monkeypatch.setattr(usage.settings, "usage_db_path", str(obstacle / "usage.sqlite"))
    monkeypatch.setattr(usage.settings, "usage_capture", True)
    monkeypatch.setattr(usage, "_echecs", 0)

    await usage.record_start(thread_id="t", endpoint="chat", question="q")

    assert usage._echecs == 1  # noqa: SLF001
    stats = await usage.stats()
    assert stats.interactions == 0
    assert stats.size_bytes == 0


@pytest.mark.asyncio
async def test_les_rappels_d_echec_sont_espaces(base, monkeypatch, caplog) -> None:
    """Journaliser à chaque requête noierait le journal et ferait perdre le reste."""
    monkeypatch.setattr(usage.aiosqlite, "connect", lambda *a, **k: 1 / 0)

    with caplog.at_level(logging.WARNING, logger="src.agent.usage"):
        for _ in range(usage._PALIER_RAPPEL + 1):  # noqa: SLF001
            await usage.record_start(thread_id="t", endpoint="chat", question="q")

    warnings = [e for e in caplog.records if e.levelno == logging.WARNING]
    assert len(warnings) == 2, "le premier échec, puis un rappel au palier"  # noqa: PLR2004


@pytest.mark.asyncio
async def test_completer_sans_ouverture_n_invente_pas_d_interaction(base, caplog) -> None:
    """Une interaction sans question ni classement serait indiscernable d'une
    génération directe : mieux vaut la perdre et le dire."""
    with caplog.at_level(logging.WARNING, logger="src.agent.usage"):
        await usage.record_completion(thread_id="jamais-ouvert", response="r")

    assert _lire(base, "SELECT COUNT(*) n FROM interactions")[0]["n"] == 0
    assert any(
        "jamais-ouvert" in enregistrement.getMessage() for enregistrement in caplog.records
    ), "perdre une observation en silence est ce que ce lot interdit"


# ─── Concurrence ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_l_initialisation_fixe_le_mode_de_journalisation(base) -> None:
    """WAL est fixé au démarrage, jamais dans le chemin d'écriture.

    Le changement de mode exige un verrou exclusif et ne respecte pas le délai
    d'attente : laissé dans le chemin d'écriture, il faisait perdre jusqu'à six
    interactions sur dix simultanées.
    """
    await usage.initialiser()

    assert _lire(base, "PRAGMA journal_mode")[0]["journal_mode"] == "wal"
    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees")[0]["n"] == 0


@pytest.mark.asyncio
async def test_deux_interactions_concurrentes_n_abiment_pas_la_base(base) -> None:
    """SQLite sérialise les écritures : sans busy_timeout, la seconde échoue.

    Dix interactions simultanées, chacune avec ses trois sources : les trente
    lignes doivent être là, et chaque interaction complète.
    """
    async def interaction(numero: int) -> None:
        thread = f"t-{numero}"
        await usage.record_start(
            thread_id=thread,
            endpoint="chat",
            question=f"question {numero}",
            ranking=[_chunk(f"aaaaaaaa{numero:02d}", 0.9),
                     _chunk(f"bbbbbbbb{numero:02d}", 0.5),
                     _chunk(f"cccccccc{numero:02d}", 0.2)],
        )
        await usage.record_completion(
            thread_id=thread,
            response=f"réponse {numero}",
            selected_element_ids=[f"aaaaaaaa{numero:02d}"],
        )

    await asyncio.gather(*(interaction(n) for n in range(10)))

    assert usage._echecs == 0, "aucune écriture perdue"  # noqa: SLF001
    assert _lire(base, "SELECT COUNT(*) n FROM interactions")[0]["n"] == 10  # noqa: PLR2004
    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees")[0]["n"] == 30  # noqa: PLR2004
    assert _lire(base, "SELECT COUNT(*) n FROM interactions WHERE completed_at IS NULL")[0][
        "n"
    ] == 0
    assert _lire(base, "SELECT COUNT(*) n FROM sources_proposees WHERE retenue = 1")[0][
        "n"
    ] == 10  # noqa: PLR2004


# ─── L'appréciation ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_l_appreciation_se_rattache_a_l_interaction(base) -> None:
    await usage.record_start(thread_id="t-note", endpoint="chat", question="q")
    resultat = await usage.record_feedback(
        thread_id="t-note", rating="inutile", comment="Répond à côté."
    )

    assert resultat == "enregistre"
    ligne = _lire(base, "SELECT rating, rating_comment, rated_at FROM interactions")[0]
    assert (ligne["rating"], ligne["rating_comment"]) == ("inutile", "Répond à côté.")
    assert ligne["rated_at"] is not None


@pytest.mark.asyncio
async def test_l_appreciation_sur_un_thread_inconnu_se_distingue_d_un_echec(base) -> None:
    """L'appelant doit pouvoir répondre 404 sans confondre avec une panne."""
    assert await usage.record_feedback(thread_id="inconnu", rating="utile") == "inconnu"


# ─── La taille de l'actif ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_chemin_vide_ne_devient_pas_le_dossier_courant(base, monkeypatch) -> None:
    """`Path("")` vaut `Path(".")`, et la sonde annonçait « . » comme base.

    C'est cosmétique, mais c'est une sonde : elle doit dire qu'aucun chemin
    n'est configuré, pas désigner un dossier où rien n'est écrit.
    """
    monkeypatch.setattr(usage.settings, "usage_db_path", "")

    etat = await usage.stats()

    assert etat.path == ""
    assert etat.enabled is False
    assert (etat.interactions, etat.size_bytes) == (0, 0)


@pytest.mark.asyncio
async def test_la_taille_est_mesurable_sans_creer_le_fichier(base) -> None:
    """Aucune purge n'existe : la taille doit être visible, et /health n'écrit pas."""
    vide = await usage.stats()
    assert (vide.interactions, vide.size_bytes) == (0, 0)
    assert not base.exists(), "mesurer ne doit pas créer"

    await usage.record_start(
        thread_id="t-taille", endpoint="chat", question="q",
        ranking=[_chunk("aaaaaaaaa1", 0.9)],
    )
    pleine = await usage.stats()

    assert (pleine.interactions, pleine.sources) == (1, 1)
    assert pleine.size_bytes > 0
    assert pleine.enabled


# ─── L'export ─────────────────────────────────────────────────────────────────

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "usage_export.py"


def _usage_export():
    """Charge scripts/usage_export.py sans faire de `scripts/` un paquet.

    Ce montage n'exerce QUE les fonctions du module. Il ne dit rien de son
    exécution comme commande — c'est ce trou qui a laissé passer un script qui
    mourait sur `ModuleNotFoundError` dès la première ligne de `main()`. D'où
    les deux tests en sous-processus plus bas.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("usage_export", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lancer_script(*arguments):
    """Exécute le script comme le ferait un humain, dans un sous-processus.

    En processus, `src` est déjà importable parce que pytest tourne depuis la
    racine : un test qui appellerait `main()` directement serait vert avec ou
    sans le `sys.path.insert` du script. Seul un sous-processus, PYTHONPATH
    retiré, reproduit la vraie invocation.
    """
    environnement = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        cwd=str(_RACINE),
        env=environnement,
        check=False,
    )


@pytest.mark.asyncio
async def test_l_export_rend_les_sources_imbriquees_dans_leur_interaction(base) -> None:
    """L'imbrication est ce qui rend les décochages lisibles sans jointure."""
    await usage.initialiser()
    await usage.record_start(
        thread_id="t-export", endpoint="chat", question="q",
        ranking=[_chunk("aaaaaaaaa1", 0.9), _chunk("aaaaaaaaa2", 0.81)],
    )
    await usage.record_completion(
        thread_id="t-export", response="r",
        submitted=[_section("aaaaaaaaa1")],
        selected_element_ids=["aaaaaaaaa1"],
    )

    document = _usage_export().exporter(base)

    assert document["schema_version"] == usage.SCHEMA_VERSION
    assert document["count"] == 1
    interaction = document["interactions"][0]
    # Les colonnes JSON sont réhydratées : sinon le lecteur reçoit des chaînes
    # échappées à l'intérieur d'un document déjà JSON.
    assert interaction["ranked_element_ids"] == ["aaaaaaaaa1", "aaaaaaaaa2"]
    assert interaction["config_json"]["ollama_model"]
    sorts = {s["element_id"]: s["retenue"] for s in interaction["sources_proposees"]}
    assert sorts == {"aaaaaaaaa1": 1, "aaaaaaaaa2": 0}


@pytest.mark.asyncio
async def test_l_export_sait_ne_garder_qu_un_chemin(base) -> None:
    """Une campagne écrit 138 interactions en `answer` : sans filtre, elles
    noient l'usage humain."""
    await usage.record_start(thread_id="t-humain", endpoint="chat", question="humaine")
    await usage.record_start(thread_id="t-campagne", endpoint="answer", question="campagne")

    export = _usage_export()

    assert [i["question"] for i in export.exporter(base, endpoint="chat")["interactions"]] == [
        "humaine"
    ]
    assert export.exporter(base)["count"] == 2  # noqa: PLR2004


def test_l_export_ne_cree_pas_la_base_qu_il_lit(tmp_path) -> None:
    """Un export doit être en lecture seule : il peut tourner pendant que le
    service écrit, et ne doit surtout pas fabriquer une base vide."""
    absente = tmp_path / "jamais_ecrite.sqlite"

    with pytest.raises(sqlite3.OperationalError):
        _usage_export().exporter(absente)

    assert not absente.exists()


@pytest.mark.asyncio
async def test_le_script_s_execute_comme_une_commande(base, tmp_path) -> None:
    """La commande de la documentation, lancée telle qu'elle est écrite.

    Le script définissait `ROOT` sans l'ajouter au chemin d'import : toute
    invocation mourait sur `ModuleNotFoundError: No module named 'src'`, y
    compris avec `--db`. Les tests précédents ne le voyaient pas — ils
    n'appelaient jamais `main()`.
    """
    await usage.record_start(
        thread_id="t-commande", endpoint="chat", question="Question réellement posée ?",
        ranking=[_chunk("aaaaaaaaa1", 0.9)],
    )
    sortie = tmp_path / "usage.json"

    resultat = _lancer_script("--db", str(base), "--out", str(sortie))

    assert resultat.returncode == 0, resultat.stderr
    assert "1 interaction(s)" in resultat.stderr
    document = json.loads(sortie.read_text(encoding="utf-8"))
    assert document["count"] == 1
    assert document["interactions"][0]["question"] == "Question réellement posée ?"
    assert document["interactions"][0]["sources_proposees"][0]["rang"] == 1


def test_le_script_rend_1_sur_une_base_absente(tmp_path) -> None:
    """Un chemin faux doit se dire, pas se planter — et ne rien créer."""
    absente = tmp_path / "jamais_ecrite.sqlite"

    resultat = _lancer_script("--db", str(absente))

    assert resultat.returncode == 1
    assert "Aucune base de capture" in resultat.stderr
    assert not absente.exists()
