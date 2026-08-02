"""Logique de retrieval indépendante de ChromaDB : déduplication, calibration,
groupement par document."""

import pytest

from src.agent.retriever import _sigmoid, dedupe_by_element, group_by_document
from src.api.schemas import ChunkResult


def _chunk(chunk_id: str, element_id: str, **kwargs) -> ChunkResult:
    base = {
        "chunk_id": chunk_id,
        "element_id": element_id,
        "graph_node_id": element_id,
        "document": "texte",
        "filename": "chapitre.html",
        "page_no": 1,
        "label": "paragraph",
        "distance": 0.5,
    }
    return ChunkResult(**{**base, **kwargs})


# ─── Calibration des scores ───────────────────────────────────────────────────

def test_sigmoid_borne_les_logits() -> None:
    assert _sigmoid(0.0) == pytest.approx(0.5)
    assert 0.0 < _sigmoid(-11.0) < 0.01  # noqa: PLR2004
    assert 0.99 < _sigmoid(11.0) < 1.0  # noqa: PLR2004


def test_sigmoid_ne_deborde_pas_sur_les_logits_extremes() -> None:
    """exp(-x) déborde pour x très négatif : la forme stable doit être utilisée."""
    assert _sigmoid(-1000.0) == pytest.approx(0.0)
    assert _sigmoid(1000.0) == pytest.approx(1.0)


# ─── Déduplication par élément ────────────────────────────────────────────────

def test_dedupe_garde_la_fenetre_la_mieux_classee() -> None:
    """Un bloc long donne plusieurs chunks de même element_id (« abc#0 », « abc#1 »)."""
    chunks = [
        _chunk("abc#0", "abc", rerank_score=1.0),
        _chunk("abc#1", "abc", rerank_score=5.0),
        _chunk("xyz", "xyz", rerank_score=3.0),
    ]
    result = dedupe_by_element(chunks)

    assert [c.element_id for c in result] == ["abc", "xyz"]
    assert result[0].chunk_id == "abc#1"


def test_dedupe_departage_par_distance_sans_rerank() -> None:
    chunks = [
        _chunk("abc#0", "abc", distance=0.9),
        _chunk("abc#1", "abc", distance=0.1),
    ]
    assert dedupe_by_element(chunks)[0].chunk_id == "abc#1"


def test_dedupe_preserve_l_ordre_d_entree() -> None:
    """Appelée après un tri, la fonction ne doit pas le défaire."""
    chunks = [_chunk(f"e{i}", f"e{i}", rerank_score=float(-i)) for i in range(5)]
    assert [c.element_id for c in dedupe_by_element(chunks)] == [f"e{i}" for i in range(5)]


# ─── Groupement par document ──────────────────────────────────────────────────

def test_group_ne_fusionne_pas_deux_chapitres_homonymes() -> None:
    """Deux ouvrages peuvent contenir une « Préface » : le chemin les distingue."""
    chunks = [
        _chunk("a", "a", filename="Preface", source_path="htms/Livre A/Preface.html",
               collection="Livre A", rerank_score=2.0),
        _chunk("b", "b", filename="Preface", source_path="htms/Livre B/Preface.html",
               collection="Livre B", rerank_score=1.0),
    ]
    groups = group_by_document(chunks)

    assert len(groups) == 2  # noqa: PLR2004
    assert {g.collection for g in groups} == {"Livre A", "Livre B"}
    assert groups[0].display_name == "Livre A > Preface"


def test_group_replie_sur_le_filename_sans_source_path() -> None:
    """Documents ingérés avant l'ajout de la métadonnée."""
    chunks = [_chunk("a", "a", rerank_score=1.0), _chunk("b", "b", rerank_score=2.0)]
    groups = group_by_document(chunks)

    assert len(groups) == 1
    assert groups[0].display_name == "chapitre.html"


def test_group_trie_par_meilleur_score_et_expose_la_pertinence() -> None:
    chunks = [
        _chunk("a", "a", source_path="x", rerank_score=-1.0, relevance=0.27),
        _chunk("b", "b", source_path="y", rerank_score=4.0, relevance=0.98),
    ]
    groups = group_by_document(chunks)

    assert [g.source_path for g in groups] == ["y", "x"]
    assert groups[0].best_relevance == pytest.approx(0.98)
