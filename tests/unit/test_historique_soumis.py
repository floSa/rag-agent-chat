"""Profondeur d'historique soumise au LLM, par route.

Trois endpoints acceptent un `chat_history` et le passent à la génération.
`chat_history` n'avait aucune borne de longueur, et /chat/simple soumettait tout
ce que le client envoyait là où /chat/start et /answer coupaient à six : la même
conversation produisait deux prompts selon la route empruntée. L'historique est
le vecteur par lequel le prompt dépassait `num_ctx` — et c'est alors Ollama qui
tranche, par le début, donc en jetant le message système.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from src.api.schemas import MAX_HISTORY_MESSAGES, SectionContext


@pytest.fixture
def soumis(monkeypatch):
    """Client /chat/simple + l'historique effectivement passé à la génération."""
    from src.agent import llm
    from src.api import main

    vu: list[list] = []

    def fake_reconstruct(element_id: str) -> SectionContext:
        return SectionContext(
            element_id=element_id,
            section_id="sssssssss1",
            breadcrumbs=[],
            elements=[],
            markdown="Le texte de la section.",
        )

    async def fake_stream(_question, _contexts, chat_history=None, **_kw) -> AsyncIterator[str]:
        vu.append(list(chat_history or []))
        yield "Réponse."

    monkeypatch.setattr(main, "reconstruct_section", fake_reconstruct)
    monkeypatch.setattr(main, "generate_stream", fake_stream)
    # La route non-streamée passe par llm.generate, qui appelle le
    # generate_stream de SON module — un autre lien que celui de main.
    monkeypatch.setattr(llm, "generate_stream", fake_stream)
    return TestClient(main.app), vu


def _historique(nb: int) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"}
        for i in range(nb)
    ]


def test_chat_simple_ne_soumet_que_les_derniers_messages(soumis) -> None:
    client, vu = soumis
    reponse = client.post(
        "/chat/simple",
        json={
            "question": "Et pour les femmes ?",
            "selected_element_ids": ["abcdef0123"],
            "chat_history": _historique(12),
            "stream": False,
        },
    )

    assert reponse.status_code == 200  # noqa: PLR2004
    assert len(vu[0]) == MAX_HISTORY_MESSAGES
    # Les plus récents : c'est le dernier échange qui situe la question.
    assert vu[0][-1].content == "message 11"


def test_un_historique_court_passe_entier(soumis) -> None:
    client, vu = soumis
    client.post(
        "/chat/simple",
        json={
            "question": "q",
            "selected_element_ids": ["abcdef0123"],
            "chat_history": _historique(2),
            "stream": False,
        },
    )

    assert len(vu[0]) == 2  # noqa: PLR2004


def test_un_historique_hors_borne_est_rejete(soumis) -> None:
    """La borne du schéma protège avant que quoi que ce soit n'atteigne le LLM."""
    from src.api.schemas import MAX_HISTORY_PAYLOAD

    client, _ = soumis
    reponse = client.post(
        "/chat/simple",
        json={
            "question": "q",
            "selected_element_ids": ["abcdef0123"],
            "chat_history": _historique(MAX_HISTORY_PAYLOAD + 1),
            "stream": False,
        },
    )

    assert reponse.status_code == 422  # noqa: PLR2004


def test_le_frontend_ne_derive_pas_de_la_borne_du_schema() -> None:
    """`src/frontend/app.py` duplique la constante : l'image du frontend ne
    contient que `src/frontend` et ne peut pas importer les schémas.

    Sans ce garde-fou, les deux valeurs divergent en silence — et le frontend
    enverrait soit plus que ce que l'API lit, soit moins que ce qu'elle accepte.
    """
    from src.frontend import app

    assert app.MAX_HISTORY_MESSAGES == MAX_HISTORY_MESSAGES

def test_l_image_du_frontend_suit_les_versions_declarees() -> None:
    """`Dockerfile.frontend` réinstalle ses dépendances à la main, sans lire
    requirements.txt : l'image tournait sur streamlit 1.44.1 et pydantic 2.11.4
    quand le dépôt déclarait tester 1.60.0 et 2.13.4.

    Une divergence entre l'image et le lock est le vieillissement silencieux que
    décrit documentation/SECURITY.md — que rien ne signalait ici.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2]
    dockerfile = (racine / "Dockerfile.frontend").read_text(encoding="utf-8")
    declarees = dict(
        ligne.split("==", 1)
        for ligne in (racine / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if "==" in ligne and not ligne.startswith("#")
    )

    for paquet in ("streamlit", "httpx", "pydantic"):
        assert f"{paquet}=={declarees[paquet]}" in dockerfile, (
            f"Dockerfile.frontend n'epingle pas {paquet}=={declarees[paquet]}"
        )
