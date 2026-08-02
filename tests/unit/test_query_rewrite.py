"""Réécriture d'une question de suivi en question autonome.

« Et pour les femmes ? » est embarqué tel quel par le modèle : le vecteur ne
porte aucun terme utile et la recherche ne retrouve rien. La réécriture restitue
le sujet avant l'encodage — mais elle passe par un LLM, donc elle doit échouer
proprement : une recherche non réécrite vaut mieux qu'une recherche sur du bruit.
"""

import pytest

from src.agent import llm
from src.api.schemas import Message

HISTORIQUE = [
    Message(role="user", content="Quel est l'écart-type des salaires des hommes ?"),
    Message(role="assistant", content="Il est de 12 000 euros."),
]


def _reponse_ollama(contenu: str):
    class Resp:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {"message": {"content": contenu}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_args, **_kwargs):
            return Resp()

    return lambda **_kwargs: Client()


@pytest.mark.asyncio
async def test_sans_historique_aucun_appel_au_llm(monkeypatch) -> None:
    """La première question d'une conversation est déjà autonome."""
    appels = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **_k: appels.append(True))

    assert await llm.rewrite_question("Quel est l'écart-type ?", []) == "Quel est l'écart-type ?"
    assert appels == []


@pytest.mark.asyncio
async def test_question_de_suivi_devient_autonome(monkeypatch) -> None:
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", _reponse_ollama("Quel est l'écart-type des salaires des femmes ?")
    )

    result = await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE)
    assert result == "Quel est l'écart-type des salaires des femmes ?"


@pytest.mark.asyncio
async def test_prefixe_bavard_du_modele_retire(monkeypatch) -> None:
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", _reponse_ollama('Question autonome : "Salaires des femmes ?"')
    )

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Salaires des femmes ?"


@pytest.mark.asyncio
async def test_seule_la_premiere_ligne_est_retenue(monkeypatch) -> None:
    """Un modèle bavard explique après avoir réécrit ; l'explication n'est pas une requête."""
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _reponse_ollama("Salaires des femmes ?\n\nJ'ai remplacé le pronom par son référent."),
    )

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Salaires des femmes ?"


@pytest.mark.asyncio
async def test_repli_sur_la_question_si_le_llm_echoue(monkeypatch) -> None:
    def boom(**_kwargs):
        raise ConnectionError("Ollama injoignable")

    monkeypatch.setattr(llm.httpx, "AsyncClient", boom)

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"


@pytest.mark.asyncio
async def test_repli_si_le_modele_repond_au_lieu_de_reecrire(monkeypatch) -> None:
    """Une sortie trop longue n'est pas une requête : c'est une réponse."""
    monkeypatch.setattr(llm.httpx, "AsyncClient", _reponse_ollama("x" * 500))

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"


@pytest.mark.asyncio
async def test_repli_si_sortie_vide(monkeypatch) -> None:
    monkeypatch.setattr(llm.httpx, "AsyncClient", _reponse_ollama("   "))

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"


@pytest.mark.asyncio
async def test_desactivable_par_reglage(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "query_rewrite", False)
    appels = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **_k: appels.append(True))

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"
    assert appels == []


# ─── Traduction pour la recherche ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_question_traduite_dans_l_autre_langue(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)
    reponse = _reponse_ollama("What is the standard deviation?")
    monkeypatch.setattr(llm.httpx, "AsyncClient", reponse)

    result = await llm.translate_question("Qu'est-ce que l'écart-type ?")
    assert result == "What is the standard deviation?"


@pytest.mark.asyncio
async def test_traduction_identique_a_l_original_ecartee(monkeypatch) -> None:
    """Le modèle rend parfois la question inchangée : rien à fusionner alors."""
    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)
    monkeypatch.setattr(llm.httpx, "AsyncClient", _reponse_ollama("Qu'est-ce que l'écart-type ?"))

    assert await llm.translate_question("Qu'est-ce que l'écart-type ?") is None


@pytest.mark.asyncio
async def test_traduction_trop_longue_ecartee(monkeypatch) -> None:
    """Une sortie démesurée n'est pas une traduction : le modèle a commenté."""
    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)
    monkeypatch.setattr(llm.httpx, "AsyncClient", _reponse_ollama("x" * 500))

    assert await llm.translate_question("Question courte ?") is None


@pytest.mark.asyncio
async def test_traduction_desactivable(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "cross_lingual_search", False)
    appels = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **_k: appels.append(True))

    assert await llm.translate_question("Question ?") is None
    assert appels == []


@pytest.mark.asyncio
async def test_repli_si_le_llm_echoue(monkeypatch) -> None:
    """Une recherche monolingue vaut mieux qu'une recherche interrompue."""
    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)

    def boom(**_kwargs):
        raise ConnectionError("Ollama injoignable")

    monkeypatch.setattr(llm.httpx, "AsyncClient", boom)

    assert await llm.translate_question("Question ?") is None
