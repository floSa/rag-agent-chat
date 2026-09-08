import pytest


@pytest.fixture(autouse=True)
def _verdict_du_modele_embedding_neuf():
    """Aucun test n'hérite du verdict de concordance établi par un autre.

    `retriever` mémorise la concordance entre le réglage et l'estampille de la
    collection, pour ne pas la relire à chaque recherche. C'est un état de
    MODULE : sans ce réarmement, un test qui l'établit rend verts tous ceux qui
    suivent sans qu'aucun garde ne regarde quoi que ce soit — le faux vert exact
    qu'un garde décoratif produirait.
    """
    from src.agent import retriever

    retriever.rearmer_verification_modele()
    yield
    retriever.rearmer_verification_modele()


@pytest.fixture
def sample_chunks():
    from src.api.schemas import ChunkResult

    return [
        ChunkResult(
            chunk_id="abc123_part0",
            element_id="abc123",
            graph_node_id="abc123",
            document="Le modèle Docling utilise un réseau de neurones pour détecter la structure.",
            filename="docling_paper.pdf",
            page_no=3,
            label="paragraph",
            minio_url=None,
            page_position=5,
            ref_position=2,
            distance=0.12,
        ),
        ChunkResult(
            chunk_id="def456_part0",
            element_id="def456",
            graph_node_id="def456",
            document="TableFormer est un modèle spécialisé pour la reconnaissance de tableaux.",
            filename="docling_paper.pdf",
            page_no=4,
            label="paragraph",
            minio_url=None,
            page_position=8,
            ref_position=1,
            distance=0.25,
        ),
        ChunkResult(
            chunk_id="ghi789_part0",
            element_id="ghi789",
            graph_node_id="ghi789",
            document="Ce document explique les bases du droit des contrats.",
            filename="autre_document.pdf",
            page_no=1,
            label="paragraph",
            minio_url=None,
            page_position=1,
            ref_position=0,
            distance=0.60,
        ),
    ]
