"""Recherche lexicale BM25 et fusion RRF.

La recherche dense rate ce qui ne se paraphrase pas : « ISO 27001 » n'a pas de
synonyme. BM25 le retrouve à la lettre. Les deux échouent sur des cas
différents, et la fusion récupère les deux — à condition de ne PAS additionner
leurs scores, qui ne vivent pas sur la même échelle.
"""

import pytest

from src.agent.lexical import (
    LexicalIndex,
    chunk_from_record,
    fuse,
    reciprocal_rank_fusion,
    tokenize,
)
from src.api.schemas import ChunkResult


def _chunk(chunk_id: str, **kwargs) -> ChunkResult:
    base = {
        "chunk_id": chunk_id,
        "element_id": chunk_id,
        "graph_node_id": chunk_id,
        "document": "texte",
        "filename": "f.html",
        "page_no": 1,
        "label": "paragraph",
        "distance": 0.5,
    }
    return ChunkResult(**{**base, **kwargs})


# ─── Découpage ────────────────────────────────────────────────────────────────

def test_accents_et_casse_neutralises() -> None:
    """Corpus mixte : « inférence » et « inference » doivent tomber sur le même jeton."""
    assert tokenize("Inférence") == tokenize("inference") == ["inference"]


def test_references_scindees_en_composants() -> None:
    """« ISO-27001 » doit être trouvable par chacun de ses morceaux."""
    assert tokenize("ISO-27001 et scikit-learn") == ["iso", "27001", "et", "scikit", "learn"]


def test_jetons_d_une_lettre_ecartes() -> None:
    assert tokenize("a b le") == ["le"]


def test_texte_vide() -> None:
    assert tokenize("   ") == []


# ─── Index BM25 ───────────────────────────────────────────────────────────────

@pytest.fixture
def index() -> LexicalIndex:
    idx = LexicalIndex()
    idx.build(
        ["c1", "c2", "c3"],
        [
            "La norme ISO 27001 encadre la sécurité de l'information.",
            "Le calcul de l'écart-type mesure la dispersion.",
            "Les conteneurs Docker isolent les dépendances.",
        ],
    )
    return idx


def test_terme_exact_retrouve(index: LexicalIndex) -> None:
    assert index.search("ISO 27001", top_k=3)[0][0] == "c1"


def test_recherche_insensible_aux_accents(index: LexicalIndex) -> None:
    assert index.search("ecart type", top_k=3)[0][0] == "c2"


def test_aucun_resultat_sans_terme_commun(index: LexicalIndex) -> None:
    assert index.search("kubernetes helm", top_k=3) == []


def test_question_vide(index: LexicalIndex) -> None:
    assert index.search("", top_k=3) == []


def test_index_non_construit_ne_leve_pas() -> None:
    assert LexicalIndex().search("quoi que ce soit", top_k=3) == []


def test_corpus_vide_laisse_l_index_inutilisable() -> None:
    """BM25Okapi divise par la longueur moyenne : un corpus vide la rendrait nulle."""
    idx = LexicalIndex()
    idx.build([], [])

    assert idx.ready is False
    assert idx.search("test", top_k=3) == []


# ─── Fusion RRF ───────────────────────────────────────────────────────────────

def test_rrf_fait_remonter_ce_qui_apparait_dans_les_deux() -> None:
    """C'est l'intérêt de la fusion, et ce qu'aucun moteur ne sait faire seul."""
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "z"]], k=60)

    assert scores["b"] > scores["a"]
    assert scores["b"] > scores["z"]


def test_rrf_ignore_l_echelle_des_scores_d_origine() -> None:
    """Seuls les rangs comptent : une distance cosine et un BM25 ne se comparent pas."""
    scores = reciprocal_rank_fusion([["a"], ["a"]], k=60)

    assert scores["a"] == pytest.approx(2 / 61)


def test_rrf_sur_un_seul_classement() -> None:
    scores = reciprocal_rank_fusion([["a", "b"]], k=60)

    assert scores["a"] > scores["b"]


def test_fuse_borne_au_top_k_et_reporte_le_score() -> None:
    denses = [_chunk("a"), _chunk("b"), _chunk("c")]
    lexicaux = [_chunk("c"), _chunk("d")]

    resultat = fuse(denses, lexicaux, top_k=2)

    assert len(resultat) == 2  # noqa: PLR2004
    assert all(c.fusion_score is not None for c in resultat)
    assert resultat[0].fusion_score >= resultat[1].fusion_score


def test_fuse_privilegie_le_chunk_dense_pour_ses_metadonnees() -> None:
    """Le dense porte la distance réelle ; le lexical la laisse à 1.0."""
    denses = [_chunk("a", distance=0.1)]
    lexicaux = [_chunk("a", distance=1.0)]

    assert fuse(denses, lexicaux, top_k=1)[0].distance == pytest.approx(0.1)


def test_fuse_sans_resultat_lexical() -> None:
    assert len(fuse([_chunk("a")], [], top_k=5)) == 1


# ─── Conversion des enregistrements ChromaDB ──────────────────────────────────

def test_chunk_lexical_porte_les_metadonnees_et_une_distance_defavorable() -> None:
    """Sans distance vectorielle, 1.0 évite qu'un départage l'avantage indûment."""
    chunk = chunk_from_record(
        "c1#0",
        "Le texte.",
        {
            "element_id": "abcdef0123",
            "graph_node_id": "abcdef0123",
            "filename": "chapitre.html",
            "collection": "Ouvrage",
            "source_path": "htms/Ouvrage/chapitre.html",
            "section_title": "Dispersion",
            "language": "fr",
            "depth": 2,
            "page_no": 42,
        },
    )

    assert chunk.chunk_id == "c1#0"
    assert chunk.element_id == "abcdef0123"
    assert chunk.collection == "Ouvrage"
    assert chunk.language == "fr"
    assert chunk.distance == 1.0
