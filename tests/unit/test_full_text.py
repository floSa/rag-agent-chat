"""Recomposition du texte intégral depuis l'index vectoriel.

Le graphe ne porte qu'un aperçu : l'ingestion y tronque le texte à 2000
caractères, le corpus complet vivant dans ChromaDB. Un tableau exporté par
Docling dépasse souvent cette limite et arrivait amputé au LLM.
"""

from src.agent import retriever
from src.agent.retriever import _join_overlapping, full_texts


# ─── Recollage des fenêtres recouvrantes ──────────────────────────────────────

def test_recouvrement_supprime_a_la_jointure() -> None:
    """L'ingestion découpe avec recouvrement : une concaténation naïve répète."""
    assert _join_overlapping(["Le chat dort sur", "dort sur le tapis."]) == (
        "Le chat dort sur le tapis."
    )


def test_morceaux_disjoints_separes_par_une_espace() -> None:
    assert _join_overlapping(["Premier.", "Second."]) == "Premier. Second."


def test_un_seul_morceau_rendu_tel_quel() -> None:
    assert _join_overlapping(["Texte entier."]) == "Texte entier."


def test_aucun_morceau() -> None:
    assert _join_overlapping([]) == ""


def test_trois_fenetres_consecutives() -> None:
    assert _join_overlapping(["aaa bbb", "bbb ccc", "ccc ddd"]) == "aaa bbb ccc ddd"


# ─── Recomposition depuis ChromaDB ────────────────────────────────────────────

def _collection(documents: list[str], metadatas: list[dict]):
    class Collection:
        def get(self, **_kwargs):
            return {"documents": documents, "metadatas": metadatas}

    return Collection()


def test_chunks_remis_dans_l_ordre_avant_recollage(monkeypatch) -> None:
    """L'index ne garantit pas l'ordre : chunk_index le rétablit."""
    monkeypatch.setattr(
        retriever,
        "_get_chroma_collection",
        lambda: _collection(
            ["milieu du texte", "du texte et la fin", "Le début et le"],
            [
                {"element_id": "abcdef0123", "chunk_index": 1},
                {"element_id": "abcdef0123", "chunk_index": 2},
                {"element_id": "abcdef0123", "chunk_index": 0},
            ],
        ),
    )

    assert full_texts(["abcdef0123"]) == {"abcdef0123": "Le début et le milieu du texte et la fin"}


def test_plusieurs_elements_recomposes_en_un_appel(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever,
        "_get_chroma_collection",
        lambda: _collection(
            ["Texte A.", "Texte B."],
            [
                {"element_id": "aaaaaaaaaa", "chunk_index": 0},
                {"element_id": "bbbbbbbbbb", "chunk_index": 0},
            ],
        ),
    )

    assert full_texts(["aaaaaaaaaa", "bbbbbbbbbb"]) == {
        "aaaaaaaaaa": "Texte A.",
        "bbbbbbbbbb": "Texte B.",
    }


def test_aucun_identifiant_n_interroge_pas_l_index(monkeypatch) -> None:
    appels = []
    monkeypatch.setattr(retriever, "_get_chroma_collection", lambda: appels.append(True))

    assert full_texts([]) == {}
    assert appels == []


def test_index_indisponible_ne_leve_pas(monkeypatch) -> None:
    """Le texte du graphe, même tronqué, vaut mieux qu'une exception."""

    def boom():
        raise ConnectionError("ChromaDB est mort")

    monkeypatch.setattr(retriever, "_get_chroma_collection", boom)

    assert full_texts(["abcdef0123"]) == {}


def test_element_absent_de_l_index_est_omis(monkeypatch) -> None:
    """Titres et fragments trop courts ne sont pas vectorisés."""
    monkeypatch.setattr(retriever, "_get_chroma_collection", lambda: _collection([], []))

    assert full_texts(["abcdef0123"]) == {}
