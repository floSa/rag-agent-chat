"""Assemblage du contexte : échappement des VIDs, fenêtrage autour de l'ancre,
rendu markdown. Aucune de ces fonctions ne touche NebulaGraph."""

from src.agent.graph_context import _build_markdown, _quote_vid, _render_element, _window_around
from src.api.schemas import BreadcrumbEntry, SectionElement


def _rows(*ids: str) -> list[dict]:
    return [{"child_id": i} for i in ids]


def _elem(node_id: str, label: str, text: str = "", **kwargs) -> SectionElement:
    return SectionElement(node_id=node_id, label=label, text=text, sequence=0, **kwargs)


# ─── Échappement des identifiants ─────────────────────────────────────────────

def test_quote_accepte_un_hash_d_element() -> None:
    assert _quote_vid("1730443c8f") == '"1730443c8f"'


def test_quote_accepte_un_vid_de_document_avec_chemin_et_accents() -> None:
    """Les VIDs de documents dérivent du chemin : séparateurs, espaces, accents."""
    vid = "doc_htms/Pratique du ML/4. Livraison continue"
    assert _quote_vid(vid) == f'"{vid}"'


def test_quote_echappe_guillemets_et_antislashs() -> None:
    """L'antislash d'abord : l'inverse produirait des séquences invalides."""
    assert _quote_vid(r'doc_a"b\c') == r'"doc_a\"b\\c"'


def test_quote_refuse_ce_qui_n_est_ni_un_hash_ni_un_document() -> None:
    assert _quote_vid('" OR 1==1 --') is None
    assert _quote_vid("NOT_A_HASH") is None


def test_quote_refuse_les_caracteres_de_controle() -> None:
    """Seuls capables de casser une littérale une fois guillemets et antislashs échappés."""
    assert _quote_vid("doc_a\nb") is None
    assert _quote_vid("doc_a\x00b") is None


def test_quote_refuse_un_vid_trop_long() -> None:
    assert _quote_vid("doc_" + "a" * 300) is None


# ─── Fenêtrage autour de l'élément trouvé ─────────────────────────────────────

def test_window_centre_sur_l_ancre() -> None:
    rows = _rows("a", "b", "c", "d", "e", "f", "g")
    window, truncated = _window_around(rows, "d", before=1, after=1)

    assert [r["child_id"] for r in window] == ["c", "d", "e"]
    assert truncated is True


def test_window_ne_tronque_pas_une_section_qui_tient() -> None:
    rows = _rows("a", "b", "c")
    window, truncated = _window_around(rows, "b", before=5, after=5)

    assert len(window) == 3  # noqa: PLR2004
    assert truncated is False


def test_window_borne_un_document_sans_section() -> None:
    """Sans SectionHeader, les enfants du Document sont le document entier."""
    rows = _rows(*[f"e{i}" for i in range(6030)])
    window, truncated = _window_around(rows, "e3000", before=6, after=6)

    assert len(window) == 13  # noqa: PLR2004
    assert truncated is True


def test_window_prend_la_tete_si_l_ancre_est_la_section_elle_meme() -> None:
    rows = _rows("a", "b", "c", "d")
    window, truncated = _window_around(rows, "introuvable", before=1, after=1)

    assert [r["child_id"] for r in window] == ["a", "b", "c"]
    assert truncated is True


def test_window_sur_section_vide() -> None:
    assert _window_around([], "a", before=3, after=3) == ([], False)


# ─── Rendu markdown ───────────────────────────────────────────────────────────

def test_element_textuel_porte_son_marqueur_de_citation() -> None:
    rendu = _render_element(_elem("abc1234567", "paragraph", "Le texte."))
    assert rendu == "Le texte. [src:abc1234567]"


def test_image_sans_url_n_est_pas_rendue() -> None:
    assert _render_element(_elem("abc1234567", "picture")) == ""


def test_image_porte_sa_legende() -> None:
    """Sans elle, le LLM reçoit un [img:ID] muet et ne peut juger sa pertinence."""
    elem = _elem(
        "abc1234567", "picture", minio_url="http://minio:9000/documents/x.png",
        caption="Répartition des revenus par décile",
    )
    rendu = _render_element(elem)

    assert "[Figure] Répartition des revenus par décile" in rendu
    assert "[img:abc1234567]" in rendu


def test_markdown_etiquette_les_sections_voisines() -> None:
    """Le LLM doit distinguer la section trouvée de ce qui l'entoure."""
    markdown = _build_markdown(
        breadcrumbs=[BreadcrumbEntry(node_id="d", label="document", text="Chapitre 4")],
        elements=[_elem("bbbbbbbbbb", "paragraph", "Au coeur.")],
        section_text="Livraison continue",
        before=[_elem("aaaaaaaaaa", "paragraph", "Fin d'avant.")],
        after=[_elem("cccccccccc", "paragraph", "Debut d'apres.")],
        before_title="Introduction",
        after_title="Packaging",
    )

    assert "[Fin de la section précédente — Introduction]" in markdown
    assert "[Début de la section suivante — Packaging]" in markdown
    assert markdown.index("Fin d'avant.") < markdown.index("Au coeur.")
    assert markdown.index("Au coeur.") < markdown.index("Debut d'apres.")


def test_markdown_vide_sans_contenu() -> None:
    assert _build_markdown([], [], "") == ""
