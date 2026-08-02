"""Tests d'intégration contre la stack réelle.

Trois des défauts les plus coûteux de ce projet n'étaient visibles qu'ici, et
aucun test unitaire ne pouvait les voir :

- une requête nGQL écrite à l'envers, qui rendait la reconstruction par le
  graphe totalement inopérante ;
- une arête renommée côté ingestion, dont l'échec était avalé et privait
  silencieusement les illustrations de leur légende ;
- un checkpointer synchrone sur un flux asynchrone, qui faisait tomber toute
  l'interface en 500.

Ils exigent les stores et le service : lancer `make test-integration` avec la
stack démarrée. Sans elle, tout est ignoré plutôt qu'en échec — un test rouge
faute d'infrastructure ne dit rien sur le code.

    make test-integration
    API_URL=http://localhost:8011 uv run pytest tests/integration -m integration
"""

from __future__ import annotations

import os

import httpx
import pytest

API_URL = os.environ.get("API_URL", "http://localhost:8011")
API_KEY = os.environ.get("API_KEY", "")

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _entetes() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


@pytest.fixture(scope="module")
def api() -> str:
    """URL de l'API, ou test ignoré si elle ne répond pas."""
    try:
        sante = httpx.get(f"{API_URL}/health", timeout=10.0).json()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"API injoignable sur {API_URL} : {exc}")
    if sante.get("status") != "ok":
        pytest.skip(f"Dépendances dégradées : {sante.get('services')}")
    return API_URL


# ─── Santé et dépendances ─────────────────────────────────────────────────────

def test_les_trois_dependances_repondent(api: str) -> None:
    services = httpx.get(f"{api}/health", timeout=10.0).json()["services"]

    assert services == {"chromadb": True, "nebulagraph": True, "ollama": True}


# ─── Recherche ────────────────────────────────────────────────────────────────

def test_la_recherche_rend_des_sources_identifiees(api: str) -> None:
    """Une source sans ouvrage ni section ne peut pas être citée correctement."""
    reponse = httpx.post(
        f"{api}/sources",
        json={"question": "What is continuous delivery for machine learning?"},
        headers=_entetes(),
        timeout=180.0,
    )
    reponse.raise_for_status()
    groupes = reponse.json()["groups"]

    assert groupes, "aucune source trouvée — l'index est-il peuplé ?"
    assert all(g["source_path"] for g in groupes), "identité du document manquante"
    assert any(c["section_title"] for g in groupes for c in g["chunks"])
    assert all(0.0 <= (c["relevance"] or 0.0) <= 1.0 for g in groupes for c in g["chunks"])


def test_un_element_n_apparait_qu_une_fois(api: str) -> None:
    """Un bloc long donne plusieurs chunks de même element_id : ils doivent fusionner."""
    reponse = httpx.post(
        f"{api}/sources",
        json={"question": "standard deviation dispersion statistics"},
        headers=_entetes(),
        timeout=180.0,
    )
    ids = [c["element_id"] for g in reponse.json()["groups"] for c in g["chunks"]]

    assert len(ids) == len(set(ids))


def test_question_francaise_atteint_le_corpus_anglais(api: str) -> None:
    """Le cas que le modèle monolingue ratait systématiquement."""
    reponse = httpx.post(
        f"{api}/answer",
        json={"question": "Comment calculer un écart-type en Python ?", "max_sources": 3},
        headers=_entetes(),
        timeout=600.0,
    )
    reponse.raise_for_status()
    corps = reponse.json()

    langues = {c["language"] for c in corps["contexts"] if c["language"]}
    assert "en" in langues, f"aucune source anglaise : {langues}"


# ─── Reconstruction par le graphe ─────────────────────────────────────────────

def test_le_contexte_reconstruit_situe_le_passage(api: str) -> None:
    """La remontée doit atteindre le Document, pas s'arrêter à la section.

    C'est ce qui échouait : `dst(edge)` sous `REVERSELY` renvoie le nœud de
    départ, la remontée n'avançait donc jamais et la section revenait vide.
    """
    sources = httpx.post(
        f"{api}/sources",
        json={"question": "continuous delivery machine learning"},
        headers=_entetes(),
        timeout=180.0,
    ).json()
    element_id = sources["groups"][0]["chunks"][0]["element_id"]

    contexte = httpx.get(f"{api}/context/{element_id}", headers=_entetes(), timeout=120.0).json()

    assert contexte["filename"], "le document n'a pas été atteint par la remontée"
    assert contexte["elements"], "la section est vide"
    assert contexte["markdown"], "aucun contexte assemblé"
    assert any(b["label"] == "document" for b in contexte["breadcrumbs"])


def test_les_elements_portent_leur_marqueur_de_citation(api: str) -> None:
    """Sans marqueur dans le prompt, le LLM ne peut citer qu'en inventant."""
    sources = httpx.post(
        f"{api}/sources",
        json={"question": "MLOps foundations"},
        headers=_entetes(),
        timeout=180.0,
    ).json()
    element_id = sources["groups"][0]["chunks"][0]["element_id"]

    markdown = httpx.get(
        f"{api}/context/{element_id}", headers=_entetes(), timeout=120.0
    ).json()["markdown"]

    assert "[src:" in markdown


# ─── Flux interactif ──────────────────────────────────────────────────────────

def test_start_puis_resume_sur_la_stack_reelle(api: str) -> None:
    """Le flux que le checkpointer synchrone faisait tomber en 500."""
    depart = httpx.post(
        f"{api}/chat/start",
        json={"question": "What is MLOps?"},
        headers=_entetes(),
        timeout=180.0,
    )
    depart.raise_for_status()
    corps = depart.json()
    element_id = corps["groups"][0]["chunks"][0]["element_id"]

    reprise = httpx.post(
        f"{api}/chat/resume",
        json={
            "thread_id": corps["thread_id"],
            "selected_element_ids": [element_id],
            "stream": False,
        },
        headers=_entetes(),
        timeout=900.0,
    )

    assert reprise.status_code == 200  # noqa: PLR2004
    assert reprise.json()["answer"].strip()


# ─── Réponse directe ──────────────────────────────────────────────────────────

def test_answer_rend_une_reponse_citable_et_chronometree(api: str) -> None:
    reponse = httpx.post(
        f"{api}/answer",
        json={"question": "What is continuous delivery for machine learning models?"},
        headers=_entetes(),
        timeout=900.0,
    )
    reponse.raise_for_status()
    corps = reponse.json()

    assert corps["answer"].strip()
    assert corps["retrieved_element_ids"], "le classement du retrieval est vide"
    assert corps["contexts"], "aucun passage soumis au LLM"
    assert corps["retrieval_ms"] > 0
    # Chaque citation doit nommer son document ET situer le passage : c'est
    # l'exigence produit, et elle se vérifie.
    for citation in corps["citations"]:
        assert citation["filename"], f"citation sans document : {citation}"
        assert citation["page_no"] or citation["section_title"], (
            f"citation non située : {citation}"
        )


def test_le_corpus_muet_fait_abstenir(api: str) -> None:
    """Un RAG qui n'admet jamais son ignorance est inutilisable."""
    reponse = httpx.post(
        f"{api}/answer",
        json={"question": "Quel est le chiffre d'affaires de l'entreprise en 2024 ?"},
        headers=_entetes(),
        timeout=900.0,
    ).json()

    texte = reponse["answer"].lower()
    assert any(m in texte for m in ("pas trouvé", "not find", "aucune information"))


# ─── Proxy média ──────────────────────────────────────────────────────────────

def test_objet_non_reference_refuse(api: str) -> None:
    """Le proxy ne doit servir que ce que le graphe référence."""
    reponse = httpx.get(
        f"{api}/media/images/inexistant/objet-invente.png", headers=_entetes(), timeout=30.0
    )

    assert reponse.status_code == 404  # noqa: PLR2004
