import pytest
from pydantic import ValidationError

from src.api.schemas import ChatRequest, SourceSelectionRequest


def test_selected_element_ids_valid() -> None:
    req = SourceSelectionRequest(
        thread_id="t1",
        question="q",
        selected_element_ids=["abc123def0"],
    )
    assert req.selected_element_ids == ["abc123def0"]
    assert req.stream is True


def test_selected_element_ids_rejects_injection() -> None:
    # Les ids sont interpolés dans du nGQL : tout format hors sha256[:10] est rejeté
    with pytest.raises(ValidationError):
        SourceSelectionRequest(
            thread_id="t1",
            question="q",
            selected_element_ids=['abc"; DROP SPACE rag_space;'],
        )


def test_selected_element_ids_rejects_wrong_length() -> None:
    with pytest.raises(ValidationError):
        SourceSelectionRequest(
            thread_id="t1",
            question="q",
            selected_element_ids=["abc123"],
        )


def test_selected_element_ids_requires_at_least_one() -> None:
    with pytest.raises(ValidationError):
        SourceSelectionRequest(thread_id="t1", question="q", selected_element_ids=[])


def test_chat_request_validates_ids_too() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="q", selected_element_ids=["NOT_AN_ID!"])


def test_search_request_accepts_chat_history() -> None:
    from src.api.schemas import SearchRequest

    req = SearchRequest(
        question="q",
        chat_history=[{"role": "user", "content": "bonjour"}],
    )
    assert req.chat_history[0].role == "user"


def test_top_k_absent_laisse_la_configuration_decider() -> None:
    """Un défaut chiffré dans le schéma écrasait le réglage du service.

    Le service était réglé sur 50 candidats et en recevait 20, parce que le
    client n'avait rien demandé — et le classement du retrieval s'en trouvait
    amputé sans qu'aucun log ne le signale.
    """
    from src.api.schemas import AnswerRequest, SearchRequest

    assert SearchRequest(question="q").top_k is None
    assert AnswerRequest(question="q").top_k is None


def test_top_k_explicite_est_respecte() -> None:
    from src.api.schemas import AnswerRequest

    assert AnswerRequest(question="q", top_k=80).top_k == 80  # noqa: PLR2004


# ─── Bornes de l'historique de conversation ───────────────────────────────────

def test_message_trop_long_rejete() -> None:
    """« question » était plafonnée à 2000 caractères, l'historique ne l'était pas.

    C'était le vecteur par lequel un prompt dépassait num_ctx — et une
    consommation non bornée sur un serveur d'inférence partagé avec d'autres
    projets.
    """
    from src.api.schemas import MAX_MESSAGE_CHARS, Message

    with pytest.raises(ValidationError):
        Message(role="user", content="x" * (MAX_MESSAGE_CHARS + 1))


def test_message_a_la_borne_accepte() -> None:
    """La borne vaut le plafond de génération : une réponse que le modèle
    pouvait produire doit pouvoir revenir dans l'historique au tour suivant."""
    from src.api.schemas import MAX_MESSAGE_CHARS, Message

    assert len(Message(role="user", content="x" * MAX_MESSAGE_CHARS).content) == MAX_MESSAGE_CHARS


def test_historique_trop_long_rejete() -> None:
    from src.api.schemas import MAX_HISTORY_PAYLOAD, SearchRequest

    trop = [{"role": "user", "content": "bonjour"}] * (MAX_HISTORY_PAYLOAD + 1)
    with pytest.raises(ValidationError):
        SearchRequest(question="q", chat_history=trop)


def test_toutes_les_requetes_a_historique_sont_bornees() -> None:
    """Trois schémas exposent chat_history : aucun ne doit rester sans borne."""
    from src.api.schemas import MAX_HISTORY_PAYLOAD, AnswerRequest, ChatRequest, SearchRequest

    for modele in (SearchRequest, ChatRequest, AnswerRequest):
        contrainte = modele.model_fields["chat_history"].metadata
        assert any(getattr(m, "max_length", None) == MAX_HISTORY_PAYLOAD for m in contrainte), (
            f"{modele.__name__}.chat_history sans max_length"
        )


def test_la_troncature_de_l_api_suit_la_borne_declaree() -> None:
    """L'API ne soumet au LLM que MAX_HISTORY_MESSAGES messages : le budget de
    contexte en dérive, et un littéral en dupliquait la valeur."""
    from src.api.schemas import MAX_HISTORY_MESSAGES, MAX_HISTORY_PAYLOAD

    assert MAX_HISTORY_MESSAGES <= MAX_HISTORY_PAYLOAD
