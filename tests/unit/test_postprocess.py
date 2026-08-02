"""Extraction des citations et des images depuis la réponse du LLM.

C'est la logique métier des sources : elle résout `[src:ID]` vers un document,
une page et une section, et `[img:ID]` vers le proxy média.
"""

from src.agent.graph import node_postprocess
from src.api.schemas import ChunkResult, SectionContext, SectionElement

MINIO_URL = "http://minio:9000/documents/images/livre/abcdef0123_picture.png"


def _context(**kwargs) -> SectionContext:
    base = {
        "element_id": "aaaaaaaaaa",
        "section_id": "sssssssss1",
        "breadcrumbs": [],
        "elements": [],
        "markdown": "",
        "filename": "4. Livraison continue",
        "section_title": "Packaging for ML Models",
    }
    return SectionContext(**{**base, **kwargs})


def _element(node_id: str, **kwargs) -> SectionElement:
    base = {"node_id": node_id, "label": "paragraph", "text": "Un passage.", "sequence": 0}
    return SectionElement(**{**base, **kwargs})


def _chunk(element_id: str, **kwargs) -> ChunkResult:
    base = {
        "chunk_id": element_id,
        "element_id": element_id,
        "graph_node_id": element_id,
        "document": "Texte du chunk.",
        "filename": "chapitre.html",
        "page_no": 7,
        "label": "paragraph",
        "distance": 0.2,
    }
    return ChunkResult(**{**base, **kwargs})


# ─── Citations ────────────────────────────────────────────────────────────────

def test_citation_issue_du_graphe_porte_document_page_et_section() -> None:
    """Le cas courant : le LLM cite un enfant de section, pas un chunk reranqué."""
    state = {
        "response": "La livraison continue automatise le déploiement [src:abcdef0123].",
        "reranked_chunks": [_chunk("9999999999", collection="Practical MLOps")],
        "enriched_contexts": [
            _context(filename="chapitre.html", elements=[_element("abcdef0123", page_no=42)])
        ],
    }
    citation = node_postprocess(state)["citations"][0]

    assert citation.filename == "chapitre.html"
    assert citation.page_no == 42  # noqa: PLR2004
    assert citation.section_title == "Packaging for ML Models"
    assert citation.collection == "Practical MLOps"
    assert citation.label == "Practical MLOps > chapitre.html, p.42, § Packaging for ML Models"


def test_citation_issue_d_un_chunk_reranque() -> None:
    state = {
        "response": "Un fait [src:abcdef0123].",
        "reranked_chunks": [
            _chunk("abcdef0123", collection="Livre", section_title="Introduction")
        ],
        "enriched_contexts": [],
    }
    citation = node_postprocess(state)["citations"][0]

    assert citation.collection == "Livre"
    assert citation.section_title == "Introduction"
    assert citation.text_excerpt == "Texte du chunk."


def test_les_elements_des_sections_voisines_sont_citables() -> None:
    """Ils figurent dans le prompt : le LLM peut légitimement s'y référer."""
    state = {
        "response": "Avant [src:1111111111] et après [src:2222222222].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(before=[_element("1111111111")], after=[_element("2222222222")])
        ],
    }
    citations = node_postprocess(state)["citations"]

    assert [c.element_id for c in citations] == ["1111111111", "2222222222"]


def test_citation_dupliquee_n_apparait_qu_une_fois() -> None:
    state = {
        "response": "Un fait [src:abcdef0123]. Le même [src:abcdef0123].",
        "reranked_chunks": [_chunk("abcdef0123")],
        "enriched_contexts": [],
    }
    assert len(node_postprocess(state)["citations"]) == 1


def test_identifiant_invente_par_le_llm_est_ignore() -> None:
    state = {
        "response": "Une affirmation sans source [src:deadbeef99].",
        "reranked_chunks": [_chunk("abcdef0123")],
        "enriched_contexts": [],
    }
    assert node_postprocess(state)["citations"] == []


def test_reponse_sans_citation() -> None:
    state = {"response": "Je n'ai pas trouvé.", "reranked_chunks": [], "enriched_contexts": []}
    result = node_postprocess(state)

    assert result["citations"] == []
    assert result["images"] == []


# ─── Images ───────────────────────────────────────────────────────────────────

def test_image_du_graphe_est_servie_par_le_proxy_media() -> None:
    """Les URLs minio:9000 ne sont pas résolvables depuis le navigateur."""
    state = {
        "response": "Voir la figure [img:abcdef0123].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(elements=[_element("abcdef0123", label="picture", minio_url=MINIO_URL)])
        ],
    }
    image = node_postprocess(state)["images"][0]

    assert image.element_id == "abcdef0123"
    assert image.minio_url == "/media/images/livre/abcdef0123_picture.png"


def test_image_sans_media_connu_est_ignoree() -> None:
    state = {
        "response": "Voir [img:abcdef0123].",
        "reranked_chunks": [],
        "enriched_contexts": [_context(elements=[_element("abcdef0123", label="picture")])],
    }
    assert node_postprocess(state)["images"] == []


def test_image_dupliquee_n_apparait_qu_une_fois() -> None:
    state = {
        "response": "[img:abcdef0123] puis encore [img:abcdef0123].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(elements=[_element("abcdef0123", label="picture", minio_url=MINIO_URL)])
        ],
    }
    assert len(node_postprocess(state)["images"]) == 1


def test_illustration_de_la_section_citee_est_affichee() -> None:
    """Le modèle n'émet presque jamais [img:] : une image n'a pas de texte.

    Mais si une affirmation vient d'une section, la figure de cette section
    illustre ce dont on parle — c'est tout l'intérêt d'avoir reconstruit la
    section.
    """
    state = {
        "response": "Le processus n'est pas linéaire [src:abcdef0123].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(
                elements=[
                    _element("abcdef0123", text="Le processus n'est pas linéaire."),
                    _element("1111111111", label="picture", minio_url=MINIO_URL),
                ]
            )
        ],
    }
    result = node_postprocess(state)

    assert [i.element_id for i in result["images"]] == ["1111111111"]


def test_section_non_citee_ne_montre_pas_ses_illustrations() -> None:
    """Sans quoi toute section reconstruite déverserait ses figures."""
    state = {
        "response": "Une affirmation sans source.",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(elements=[_element("1111111111", label="picture", minio_url=MINIO_URL)])
        ],
    }

    assert node_postprocess(state)["images"] == []


def test_nombre_d_illustrations_borne(monkeypatch) -> None:
    from src.agent import graph as graph_module

    monkeypatch.setattr(graph_module.settings, "max_images", 2)
    elements = [_element("abcdef0123", text="Un fait.")] + [
        _element(f"{i}" * 10, label="picture", minio_url=MINIO_URL) for i in range(1, 6)
    ]
    state = {
        "response": "Un fait [src:abcdef0123].",
        "reranked_chunks": [],
        "enriched_contexts": [_context(elements=elements)],
    }

    assert len(node_postprocess(state)["images"]) == 2  # noqa: PLR2004


def test_image_non_dupliquee_entre_les_deux_voies() -> None:
    """Marqueur explicite ET illustration de section citée."""
    state = {
        "response": "[img:1111111111] et un fait [src:abcdef0123].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(
                elements=[
                    _element("abcdef0123", text="Un fait."),
                    _element("1111111111", label="picture", minio_url=MINIO_URL),
                ]
            )
        ],
    }

    assert len(node_postprocess(state)["images"]) == 1


# ─── Plusieurs sources dans un même crochet ───────────────────────────────────

def test_crochet_groupant_plusieurs_sources() -> None:
    """Le modèle écrit volontiers « [src:aaa, src:bbb] ».

    Le motif exigeant le crochet fermant juste après l'identifiant ne matchait
    alors RIEN — ni la première source ni les suivantes — et le marqueur restait
    affiché tel quel dans la réponse.
    """
    state = {
        "response": "Deux sources [src:abcdef0123, src:1111111111].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(elements=[_element("abcdef0123"), _element("1111111111")])
        ],
    }

    assert [c.element_id for c in node_postprocess(state)["citations"]] == [
        "abcdef0123",
        "1111111111",
    ]


def test_crochet_groupe_sans_repetition_du_prefixe() -> None:
    """Variante rencontrée : « [src:aaa, bbb] »."""
    state = {
        "response": "Deux sources [src:abcdef0123, 1111111111].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(elements=[_element("abcdef0123"), _element("1111111111")])
        ],
    }

    assert len(node_postprocess(state)["citations"]) == 2  # noqa: PLR2004


def test_ordre_du_texte_preserve_sans_doublon() -> None:
    state = {
        "response": "[src:1111111111] puis [src:abcdef0123, src:1111111111].",
        "reranked_chunks": [],
        "enriched_contexts": [
            _context(elements=[_element("abcdef0123"), _element("1111111111")])
        ],
    }

    assert [c.element_id for c in node_postprocess(state)["citations"]] == [
        "1111111111",
        "abcdef0123",
    ]
