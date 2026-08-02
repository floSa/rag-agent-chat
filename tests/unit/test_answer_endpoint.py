"""Endpoint /answer : le point d'entrée non interactif.

Le flux interactif attend un humain et n'est donc pas rejouable en batch. C'est
cet endpoint que consomme une campagne d'évaluation : il doit rendre non
seulement la réponse, mais les passages réellement soumis au LLM et le temps
passé à chaque étage — sans quoi on ne sait pas attribuer un échec au retrieval
ou à la génération.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.schemas import Citation, SectionContext


@pytest.fixture
def client(monkeypatch):
    from src.api import main

    chunk = _chunk()

    async def fake_ainvoke(_state, _config=None):
        return {
            "response": "La dispersion se mesure par l'écart-type [src:abcdef0123].",
            "enriched_contexts": [
                SectionContext(
                    element_id="abcdef0123",
                    section_id="sssssssss1",
                    breadcrumbs=[],
                    elements=[],
                    markdown="Le texte de la section.",
                    filename="3. Python's Statistical Toolbox",
                    section_title="Dispersion",
                )
            ],
            "citations": [
                Citation(
                    element_id="abcdef0123",
                    filename="3. Python's Statistical Toolbox",
                    collection="The Statistics Workshop",
                    section_title="Dispersion",
                    page_no=88,
                    text_excerpt="extrait",
                )
            ],
            "images": [],
            "search_count": 1,
        }

    monkeypatch.setattr(main, "retrieve", lambda _q, _k=20: [chunk])
    monkeypatch.setattr(main, "rerank", lambda _q, chunks: chunks)
    monkeypatch.setattr(main.answer_graph, "ainvoke", fake_ainvoke)
    return TestClient(main.app)


def _chunk():
    from src.api.schemas import ChunkResult

    return ChunkResult(
        chunk_id="abcdef0123",
        element_id="abcdef0123",
        graph_node_id="abcdef0123",
        document="texte",
        filename="3. Python's Statistical Toolbox",
        collection="The Statistics Workshop",
        source_path="htms/The Statistics Workshop/3. Python's Statistical Toolbox.html",
        section_title="Dispersion",
        language="en",
        page_no=88,
        label="paragraph",
        distance=0.2,
        rerank_score=3.0,
        relevance=0.95,
    )


def test_answer_rend_la_reponse_et_ses_citations(client) -> None:
    body = client.post("/answer", json={"question": "Comment mesurer la dispersion ?"}).json()

    assert body["answer"].startswith("La dispersion")
    assert body["citations"][0]["collection"] == "The Statistics Workshop"
    assert body["citations"][0]["page_no"] == 88  # noqa: PLR2004


def test_answer_expose_les_passages_soumis_au_llm(client) -> None:
    """Sans eux, un évaluateur ne peut pas distinguer les deux causes d'échec."""
    body = client.post("/answer", json={"question": "Comment mesurer la dispersion ?"}).json()
    ctx = body["contexts"][0]

    assert ctx["element_id"] == "abcdef0123"
    assert ctx["text"] == "Le texte de la section."
    assert ctx["language"] == "en"
    assert ctx["source_path"].endswith("3. Python's Statistical Toolbox.html")
    assert ctx["relevance"] == pytest.approx(0.95)


def test_answer_chronometre_les_deux_etages(client) -> None:
    body = client.post("/answer", json={"question": "Comment mesurer la dispersion ?"}).json()

    assert body["retrieval_ms"] >= 0
    assert body["generation_ms"] >= 0
    assert "dropped_contexts" in body


def test_answer_refuse_une_question_vide(client) -> None:
    assert client.post("/answer", json={"question": ""}).status_code == 422  # noqa: PLR2004


def test_answer_borne_le_nombre_de_sources(client) -> None:
    assert client.post(
        "/answer", json={"question": "q", "max_sources": 99}
    ).status_code == 422  # noqa: PLR2004
