import pytest
from pydantic import ValidationError

from src.api.schemas import (
    ChatRequest,
    ChunkResult,
    SearchRequest,
    SourceSelectionRequest,
)


def test_search_request_valid() -> None:
    req = SearchRequest(question="Comment Docling gère les tableaux ?")
    assert req.top_k == 20  # valeur par défaut


def test_search_request_empty_question() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(question="")


def test_chunk_result_optional_fields() -> None:
    chunk = ChunkResult(
        chunk_id="abc_part0",
        element_id="abc",
        graph_node_id="abc",
        document="Texte du chunk",
        filename="doc.pdf",
        page_no=1,
        label="paragraph",
        distance=0.15,
    )
    assert chunk.minio_url is None
    assert chunk.rerank_score is None


def test_source_selection_requires_at_least_one() -> None:
    with pytest.raises(ValidationError):
        SourceSelectionRequest(question="test", selected_element_ids=[])


def test_chat_request_defaults() -> None:
    req = ChatRequest(question="Ma question")
    assert req.stream is True
    assert req.chat_history == []
    assert req.selected_element_ids == []
