"""Flux interactif : /chat/start → sélection → /chat/resume.

Ce flux n'était couvert par aucun test, et c'est ce qui a laissé passer un
`SqliteSaver` synchrone sur des appels `ainvoke` / `astream` : LangGraph lève
alors `NotImplementedError`, et toute l'interface tombait en 500 sans qu'aucun
test unitaire ne bronche.

Le graphe réel est exécuté — c'est le point. Seules les frontières sont
neutralisées : recherche, reconstruction et génération.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.api.schemas import ChunkResult, SectionContext, SectionElement


def _chunk(element_id: str) -> ChunkResult:
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
        relevance=0.95,
    )


def _section(element_id: str) -> SectionContext:
    """Section reconstruite, marqueur compris.

    Le markdown PORTE le marqueur de son élément, comme celui que
    `_render_element` produit en production. Sans lui, la résolution des
    citations — qui lit désormais les marqueurs du texte soumis — ne trouverait
    rien à résoudre, et ce faux ne ressemblerait plus à ce qu'il remplace.
    """
    return SectionContext(
        element_id=element_id,
        section_id="sssssssss1",
        breadcrumbs=[],
        elements=[
            SectionElement(
                node_id=element_id, label="paragraph", text="Le contexte reconstruit.", sequence=0
            )
        ],
        markdown=f"Le contexte reconstruit. [src:{element_id}]",
        filename="3. Statistical Toolbox",
        section_title="Dispersion",
    )


@pytest.fixture
def client(monkeypatch):
    from src.agent import graph as graph_module
    from src.agent.llm import fit_prompt
    from src.api import main

    # Checkpointer en mémoire : le test porte sur le flux, pas sur le stockage.
    monkeypatch.setattr(main.settings, "checkpoint_db_path", "")
    monkeypatch.setattr(
        graph_module,
        "retrieve",
        lambda _q, top_k=None, translation=None, chrono=None: [
            _chunk("abcdef0123"), _chunk("bbbbbbbbbb"),
        ],
    )
    monkeypatch.setattr(graph_module, "rerank", lambda _q, chunks: chunks)
    monkeypatch.setattr(graph_module, "reconstruct_section", _section)

    async def pas_de_reecriture(question, _history):
        return question

    async def pas_de_traduction(_question):
        return None

    async def generation(**kwargs):
        # Le faux appelle `on_fit` avec le VRAI budget, comme le fait
        # `generate_stream` avant sa requête HTTP. Sans ce rappel, l'état ne
        # porte aucune section soumise et plus aucune citation ne se résout : un
        # faux qui ne ressemble pas à la fonction qu'il remplace ne prouve rien
        # de ce qui l'appelle.
        if kwargs.get("on_fit"):
            kwargs["on_fit"](
                fit_prompt(
                    kwargs.get("question", ""),
                    kwargs.get("contexts") or [],
                    kwargs.get("chat_history"),
                )
            )
        for token in ("La dispersion ", "se mesure [src:abcdef0123]."):
            yield token

    monkeypatch.setattr(graph_module, "rewrite_question", pas_de_reecriture)
    monkeypatch.setattr(graph_module, "translate_question", pas_de_traduction)
    monkeypatch.setattr(graph_module, "generate_stream", generation)

    # Le lifespan ouvre le checkpointer : sans le gestionnaire de contexte, il
    # ne s'exécute pas et les routes répondraient 503.
    with TestClient(main.app) as testclient:
        yield testclient


def test_start_suspend_et_rend_les_sources(client) -> None:
    body = client.post("/chat/start", json={"question": "Comment mesurer la dispersion ?"}).json()

    assert body["thread_id"]
    assert body["groups"][0]["collection"] == "The Statistics Workshop"
    assert body["groups"][0]["chunks"][0]["relevance"] == pytest.approx(0.95)


def test_resume_reprend_la_session_et_genere(client) -> None:
    """Le cas qui échouait : reprendre exige un checkpointer asynchrone."""
    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]

    reponse = client.post(
        "/chat/resume",
        json={"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": False},
    )

    assert reponse.status_code == 200  # noqa: PLR2004
    body = reponse.json()
    assert "La dispersion se mesure" in body["answer"]
    assert body["citations"][0]["filename"] == "3. Statistical Toolbox"


def test_resume_en_streaming_emet_les_tokens_puis_le_final(client) -> None:
    thread = client.post("/chat/start", json={"question": "q"}).json()["thread_id"]

    with client.stream(
        "POST",
        "/chat/resume",
        json={"thread_id": thread, "selected_element_ids": ["abcdef0123"], "stream": True},
    ) as flux:
        evenements = [
            json.loads(ligne[len("data:") :].strip())
            for ligne in flux.iter_lines()
            if ligne.startswith("data:")
        ]

    assert any("token" in e for e in evenements)
    final = [e for e in evenements if e.get("done")][-1]
    assert "La dispersion se mesure" in final["answer"]
    assert final["citations"][0]["section_title"] == "Dispersion"


def test_resume_sur_session_inconnue_repond_404(client) -> None:
    reponse = client.post(
        "/chat/resume",
        json={"thread_id": "inexistant", "selected_element_ids": ["abcdef0123"], "stream": False},
    )

    assert reponse.status_code == 404  # noqa: PLR2004


def test_selection_vide_refusee_par_le_schema(client) -> None:
    reponse = client.post(
        "/chat/resume", json={"thread_id": "t", "selected_element_ids": [], "stream": False}
    )

    assert reponse.status_code == 422  # noqa: PLR2004


# ─── Le checkpointer sur disque ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkpointer_sur_disque_supporte_l_async(tmp_path, monkeypatch) -> None:
    """Le test qui aurait attrapé le bug.

    Les tests précédents tournent sur un checkpointer en mémoire, qui supporte
    l'async : ils passaient alors même que la version sur disque levait
    `NotImplementedError` sur chaque appel `aput`. Ici c'est la vraie base
    SQLite qui est ouverte, et une écriture asynchrone est tentée.
    """
    from src.agent.graph import build_checkpointer
    from src.agent.settings import settings

    monkeypatch.setattr(settings, "checkpoint_db_path", str(tmp_path / "cp.sqlite"))
    saver = await build_checkpointer()

    config = {"configurable": {"thread_id": "t-async", "checkpoint_ns": ""}}
    checkpoint = {
        "v": 1,
        "id": "c1",
        "ts": "2026-08-02T00:00:00+00:00",
        "channel_values": {"question": "q"},
        "channel_versions": {},
        "versions_seen": {},
    }

    await saver.aput(config, checkpoint, {"source": "input", "step": 0}, {})
    relu = await saver.aget_tuple(config)

    assert relu is not None
    assert relu.checkpoint["channel_values"]["question"] == "q"
