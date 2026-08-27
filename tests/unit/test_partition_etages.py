"""La partition du temps, exercée sur les VRAIS nœuds.

`test_chronometrie.py` vérifie l'arithmétique de la partition. Ici on vérifie
qu'elle est réellement alimentée : que chaque étage reçoit le temps de l'étape
qu'il nomme, et pas celui d'une autre. Un `decomposer` correct branché sur rien
publierait huit zéros et un résidu égal au total — et le tableau s'afficherait
comme si tout allait bien.

Chaque étape simulée dort une durée qui lui est propre. C'est ce qui permet
d'exiger le SENS de l'attribution : si `reconstruction_ms` recevait le temps de
la génération, les durées ne correspondraient plus.
"""

import importlib.util
import pathlib
import time

import pytest

from src.agent import graph as graph_module
from src.agent import retriever as retriever_module
from src.agent.chronometrie import ETAGES, Chrono, decomposer
from src.api.schemas import BreadcrumbEntry, ChunkResult, SectionContext, StageTimings

_RACINE_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"

QUESTION = "Comment se mesure la dispersion ?"

# Assez long pour être mesurable en millisecondes sur une machine chargée, assez
# court pour que la suite reste rapide.
LENT_MS = 30


def _chunk(element_id: str) -> ChunkResult:
    return ChunkResult(
        chunk_id=f"{element_id}_part0",
        element_id=element_id,
        graph_node_id=element_id,
        document="La dispersion se mesure par l'écart-type.",
        filename="3. Statistical Toolbox",
        source_path="htms/The Statistics Workshop/3. Statistical Toolbox.html",
        page_no=88,
        label="paragraph",
        distance=0.2,
    )


def _section(element_id: str) -> SectionContext:
    return SectionContext(
        element_id=element_id,
        section_id=f"sec{element_id[-7:]}",
        breadcrumbs=[BreadcrumbEntry(node_id="doc0000001", label="Document", text="Atelier")],
        elements=[],
        markdown="Le contexte reconstruit.",
        filename="3. Statistical Toolbox",
        section_title="Dispersion",
    )


def _dormir(ms: int):
    def _appel(*_args, **_kwargs):
        time.sleep(ms / 1000)
        return []
    return _appel


# ─── La recherche : trois étages là où il y en avait un ──────────────────────

def test_la_recherche_dense_et_la_lexicale_se_mesurent_separement(monkeypatch) -> None:
    """« Dense seul vs hybride » ne peut pas s'arbitrer sur le prix tant que les
    deux sont noyés dans le même `retrieval_ms`."""
    def dense(_q, _k):
        time.sleep(LENT_MS / 1000)
        return [_chunk("aaaaaaaaa1")]

    def lexical(_q, _k):
        time.sleep(2 * LENT_MS / 1000)
        return [_chunk("aaaaaaaaa2")]

    monkeypatch.setattr(retriever_module, "_dense_search", dense)
    monkeypatch.setattr(retriever_module, "_lexical_search", lexical)
    chrono = Chrono()

    retriever_module.retrieve(QUESTION, top_k=5, chrono=chrono)

    assert chrono.etages["dense_ms"] >= LENT_MS
    assert chrono.etages["lexical_ms"] >= 2 * LENT_MS
    # Le sens de l'attribution, pas seulement sa présence : la lexicale est
    # deux fois plus lente ici, et le tableau doit le dire.
    assert chrono.etages["lexical_ms"] > chrono.etages["dense_ms"]


def test_la_traduction_double_le_temps_de_recherche_et_cela_se_lit(monkeypatch) -> None:
    """La recherche translingue lance un classement de plus par moteur. C'est un
    coût réel, et l'ablation « avec / sans traduction » doit pouvoir le lire."""
    monkeypatch.setattr(retriever_module, "_dense_search", _dormir(LENT_MS))
    monkeypatch.setattr(retriever_module, "_lexical_search", _dormir(LENT_MS))

    sans = Chrono()
    retriever_module.retrieve(QUESTION, top_k=5, chrono=sans)
    avec = Chrono()
    retriever_module.retrieve(QUESTION, top_k=5, translation="How is spread measured?",
                              chrono=avec)

    assert avec.etages["dense_ms"] >= 2 * sans.etages["dense_ms"] * 0.8
    assert avec.etages["lexical_ms"] >= 2 * sans.etages["lexical_ms"] * 0.8


def test_la_fusion_est_facturee_a_part(monkeypatch) -> None:
    monkeypatch.setattr(retriever_module, "_dense_search", lambda _q, _k: [_chunk("aaaaaaaaa1")])
    monkeypatch.setattr(retriever_module, "_lexical_search", lambda _q, _k: [_chunk("aaaaaaaaa2")])

    def fusion_lente(classements, k, poids=None):
        time.sleep(LENT_MS / 1000)
        return classements[0][:k]

    monkeypatch.setattr(retriever_module, "fuse", fusion_lente)
    chrono = Chrono()

    retriever_module.retrieve(QUESTION, top_k=5, chrono=chrono)

    assert chrono.etages["fusion_ms"] >= LENT_MS


def test_le_temps_mural_du_noeud_contient_les_trois_etages(monkeypatch) -> None:
    """`retrieval_ms` est l'agrégat, et il doit RESTER un majorant. Le jour où il
    devient plus petit que la somme des trois, l'un d'eux mesure autre chose que
    ce qu'il dit."""
    monkeypatch.setattr(graph_module, "retrieve", retriever_module.retrieve)
    monkeypatch.setattr(retriever_module, "_dense_search", _dormir(LENT_MS))
    monkeypatch.setattr(retriever_module, "_lexical_search", _dormir(LENT_MS))

    resultat = graph_module.node_retrieve(
        {"question": QUESTION, "search_count": 0, "_metadata": {}}
    )
    etages = resultat["_metadata"]

    somme = etages["dense_ms"] + etages["lexical_ms"] + etages.get("fusion_ms", 0)
    assert etages["retrieval_ms"] >= somme


# ─── L'étage qui n'avait jamais été chronométré ───────────────────────────────

def test_la_reconstruction_par_le_graphe_est_chronometree(monkeypatch) -> None:
    """Le pari central du projet, et le seul étage sans prix connu.

    On ne peut pas arbitrer la suppression d'une étape dont on ignore le coût :
    c'est ce chiffre que l'ablation « avec / sans graphe » va lire.
    """
    def reconstruction_lente(eid):
        time.sleep(LENT_MS / 1000)
        return _section(eid)

    monkeypatch.setattr(graph_module, "reconstruct_section", reconstruction_lente)

    resultat = graph_module.node_reconstruct_context(
        {
            "reranked_chunks": [_chunk("aaaaaaaaa1"), _chunk("aaaaaaaaa2")],
            "selected_element_ids": [],
            "search_count": 1,
            "max_sources": 2,
            "_metadata": {},
        }
    )

    assert len(resultat["enriched_contexts"]) == 2
    # Deux sections reconstruites, donc deux fois le coût : la mesure est
    # cumulative par élément, pas un forfait par nœud.
    assert resultat["_metadata"]["reconstruction_ms"] >= 2 * LENT_MS


def test_une_reconstruction_qui_echoue_coute_quand_meme_son_temps(monkeypatch) -> None:
    """Une source illisible est absorbée — elle ne doit pas emporter la réponse.
    Mais elle a coûté un aller-retour Nebula, et l'étage doit le facturer :
    sinon un graphe en panne s'affiche gratuit, ce qui est le contraire du vrai."""
    def echec(_eid):
        time.sleep(LENT_MS / 1000)
        raise RuntimeError("section illisible")

    monkeypatch.setattr(graph_module, "reconstruct_section", echec)

    resultat = graph_module.node_reconstruct_context(
        {
            "reranked_chunks": [_chunk("aaaaaaaaa1")],
            "selected_element_ids": [],
            "search_count": 1,
            "max_sources": 1,
            "_metadata": {},
        }
    )

    assert resultat["enriched_contexts"] == []
    assert resultat["_metadata"]["reconstruction_ms"] >= LENT_MS


def test_sans_reconstruction_l_etage_tombe_a_zero(monkeypatch) -> None:
    """**Ce que vaudrait « pire », dans l'autre sens.**

    L'ablation du graphe est ce que ce lot doit rendre lisible : sans
    reconstruction, l'étage vaut zéro et le temps se déplace ailleurs. Un étage
    qui afficherait un chiffre non nul sans qu'aucune section soit reconstruite
    ne mesurerait pas la reconstruction.
    """
    resultat = graph_module.node_reconstruct_context(
        {
            "reranked_chunks": [],
            "selected_element_ids": [],
            "search_count": 1,
            "max_sources": 3,
            "_metadata": {},
        }
    )

    assert resultat["enriched_contexts"] == []
    assert resultat["_metadata"].get("reconstruction_ms", 0) == 0


# ─── Réécriture et traduction, deux appels LLM distincts ─────────────────────

@pytest.mark.asyncio
async def test_la_reecriture_et_la_traduction_sont_deux_etages(monkeypatch) -> None:
    """Deux coûts qui s'arbitrent séparément : la réécriture est le prix des
    questions de suivi, la traduction celui de la recherche translingue."""
    async def reecrire(question, _historique):
        time.sleep(LENT_MS / 1000)
        return question

    async def traduire(_question):
        time.sleep(3 * LENT_MS / 1000)
        return "How is spread measured?"

    monkeypatch.setattr(graph_module, "rewrite_question", reecrire)
    monkeypatch.setattr(graph_module, "translate_question", traduire)

    resultat = await graph_module.node_rewrite(
        {"question": QUESTION, "chat_history": [], "search_query": None, "_metadata": {}}
    )
    etages = resultat["_metadata"]

    assert etages["rewrite_ms"] >= LENT_MS
    assert etages["translation_ms"] >= 3 * LENT_MS
    assert etages["translation_ms"] > etages["rewrite_ms"]


@pytest.mark.asyncio
async def test_une_question_deja_reecrite_ne_coute_aucun_etage(monkeypatch) -> None:
    """Le nœud court-circuite : les deux étages doivent alors valoir zéro, pas
    un forfait."""
    resultat = await graph_module.node_rewrite(
        {"question": QUESTION, "search_query": QUESTION, "_metadata": {}}
    )

    assert resultat == {}


# ─── L'invariant, au niveau où il compte ─────────────────────────────────────

def test_le_schema_publie_exactement_les_etages_de_la_partition() -> None:
    """Deux endroits qui doivent s'accorder et que rien ne force à s'accorder :
    `ETAGES` décide de la partition, `StageTimings` la publie. Un étage ajouté
    d'un seul côté serait mesuré sans être lu, ou lu sans être mesuré."""
    publies = set(StageTimings.model_fields) - {"residual_ms", "total_ms"}

    assert publies == set(ETAGES)


def test_le_resume_de_campagne_porte_les_deux_centiles_de_chaque_etage() -> None:
    """Asserté depuis `resumer`, qui les PRODUIT — pas depuis la liste des étages.

    `test_coherence_depot` vérifie que la campagne connaît les bons noms d'étages ;
    il resterait vert si `resumer` cessait de publier la table de latence. Une
    moyenne de latence cache la queue, et c'est la queue qui décide de
    l'expérience : les deux centiles sont le contrat, pas un confort.
    """
    chemin = _RACINE_SCRIPTS / "evaluate.py"
    spec = importlib.util.spec_from_file_location("evaluate", chemin)
    assert spec and spec.loader
    evaluate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluate)

    ligne = evaluate.evaluer(
        {"id": "G-001", "gold_element_ids": ["aaaaaaaaa1"], "language": "fr"},
        {
            "contexts": [],
            "citations": [],
            "answer": "r",
            "timings": {"dense_ms": 90, "generation_ms": 4400, "residual_ms": 30,
                        "total_ms": 4520},
        },
    )
    resume = evaluate.resumer([ligne])

    for etage in StageTimings.model_fields:
        assert f"{etage}_p50" in resume, etage
        assert f"{etage}_p95" in resume, etage
    assert resume["dense_ms_p50"] == 90
    assert resume["residual_ms_p95"] == 30


def test_l_invariant_tient_sur_une_traversee_complete() -> None:
    """Le chronométrage tel qu'un `/answer` réel le rend, confronté au temps
    mural : c'est le seul chiffre qui ne dépend d'aucune instrumentation."""
    chronometrage = {
        "rewrite_ms": 210,
        "translation_ms": 180,
        "dense_ms": 90,
        "lexical_ms": 40,
        "fusion_ms": 5,
        "rerank_ms": 320,
        "reconstruction_ms": 150,
        "generation_ms": 4400,
        # L'agrégat que la capture d'usage lit, présent et ignoré.
        "retrieval_ms": 140,
    }
    etapes = StageTimings(**decomposer(chronometrage, total_ms=5500))

    somme = sum(getattr(etapes, cle) for cle in ETAGES)
    assert somme + etapes.residual_ms == etapes.total_ms
    assert etapes.residual_ms == 105
