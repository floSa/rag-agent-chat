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
        # Le graphe rend lui-même les chunks reranqués : /answer n'exécute plus
        # le retrieval de son côté, il lit le résultat d'un unique passage.
        return {
            "reranked_chunks": [chunk],
            "_metadata": {"retrieval_ms": 120, "rerank_ms": 80, "generation_ms": 900},
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
            # `dropped_contexts` n'est PAS fourni ici : c'est node_generate qui le
            # chiffre, et le lui souffler ferait de l'assertion un passe-plat sur
            # une constante de ce stub. Absent de l'état, l'endpoint doit rendre 0
            # — et le cas non trivial est couvert plus bas, sur la vraie chaîne.
        }

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
    """Les nœuds se chronomètrent eux-mêmes ; retrieval agrège recherche et rerank."""
    body = client.post("/answer", json={"question": "Comment mesurer la dispersion ?"}).json()

    assert body["retrieval_ms"] == 200  # noqa: PLR2004  120 + 80
    assert body["generation_ms"] == 900  # noqa: PLR2004
    assert body["dropped_contexts"] == 0


def test_answer_refuse_une_question_vide(client) -> None:
    assert client.post("/answer", json={"question": ""}).status_code == 422  # noqa: PLR2004


def test_answer_borne_le_nombre_de_sources(client) -> None:
    assert client.post(
        "/answer", json={"question": "q", "max_sources": 99}
    ).status_code == 422  # noqa: PLR2004


def test_answer_publie_le_chiffre_calcule_par_le_graphe(monkeypatch) -> None:
    """`dropped_contexts` doit venir de node_generate, pas d'un recalcul ni d'une
    valeur en dur.

    L'endpoint le recalculait de son côté ; le refactor `on_fit` a supprimé ce
    doublon mais laissé la chaîne sans test, et deux mutations passaient — `0` en
    dur dans node_generate, et `on_fit` jamais appelé. C'est le nombre que la
    campagne publie sous `contextes_ecartes`.

    Seule la couche HTTP est simulée : le budget est calculé par le vrai
    `fit_prompt`, à travers le vrai `generate_stream` et le vrai `node_generate`.
    """
    from src.agent import graph as graph_module
    from src.agent import llm
    from src.agent.llm import fit_prompt
    from src.api import main

    question = "Comment mesurer la dispersion ?"
    contextes = [
        SectionContext(
            element_id=f"abcdef01{i:02d}",
            section_id=f"sssssssss{i}",
            breadcrumbs=[],
            elements=[],
            markdown="x" * 4000,
        )
        for i in range(6)
    ]
    attendu = fit_prompt(question, contextes, []).dropped_contexts
    assert attendu > 0, "le cas de test ne provoque aucune mise à l'écart"

    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_ollama_minimal())

    async def fake_ainvoke(state, _config=None):
        # Le vrai nœud de génération, pour que le chiffre soit calculé et non
        # fourni : c'est toute la chaîne on_fit → état → endpoint qui est en jeu.
        etat = {**state, "enriched_contexts": contextes, "search_count": 0, "_metadata": {}}
        return {
            "reranked_chunks": [],
            "enriched_contexts": contextes,
            "citations": [],
            "images": [],
            **await graph_module.node_generate(etat),
        }

    monkeypatch.setattr(main.answer_graph, "ainvoke", fake_ainvoke)
    body = TestClient(main.app).post("/answer", json={"question": question}).json()

    assert body["dropped_contexts"] == attendu


def _flux_ollama_minimal():
    """Client httpx simulé : un flux Ollama de deux événements."""
    import json as _json

    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            yield _json.dumps({"message": {"content": "Une réponse."}})
            yield _json.dumps({"message": {"content": ""}, "done": True})

    class Stream:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *_):
            return False

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, *_args, **_kwargs):
            return Stream()

    return lambda **_kwargs: Client()
