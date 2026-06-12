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
