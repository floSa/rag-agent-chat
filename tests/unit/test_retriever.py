from src.api.schemas import ChunkResult
from src.agent.retriever import group_by_document


def test_group_by_document_groups_correctly(sample_chunks: list[ChunkResult]) -> None:
    # Affecter des scores de reranking
    sample_chunks[0].rerank_score = 0.92
    sample_chunks[1].rerank_score = 0.75
    sample_chunks[2].rerank_score = 0.30

    groups = group_by_document(sample_chunks)

    # 2 documents différents
    assert len(groups) == 2  # noqa: PLR2004

    # Le premier groupe doit être docling_paper.pdf (meilleur score)
    assert groups[0].filename == "docling_paper.pdf"
    assert groups[0].best_score == 0.92
    assert len(groups[0].chunks) == 2  # noqa: PLR2004

    # Deuxième groupe
    assert groups[1].filename == "autre_document.pdf"
    assert groups[1].best_score == 0.30


def test_group_by_document_empty() -> None:
    groups = group_by_document([])
    assert groups == []


def test_group_by_document_single_chunk(sample_chunks: list[ChunkResult]) -> None:
    sample_chunks[0].rerank_score = 0.85
    groups = group_by_document([sample_chunks[0]])
    assert len(groups) == 1
    assert groups[0].filename == "docling_paper.pdf"
    assert groups[0].best_score == 0.85
