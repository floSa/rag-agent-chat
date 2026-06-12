from src.agent.graph_context import _build_markdown
from src.api.schemas import BreadcrumbEntry, SectionElement


def test_build_markdown_with_breadcrumbs_and_elements() -> None:
    breadcrumbs = [
        BreadcrumbEntry(node_id="doc_test", label="Document", text="test.pdf"),
        BreadcrumbEntry(node_id="sec1", label="SectionHeader", text="3. Architecture"),
    ]
    elements = [
        SectionElement(
            node_id="para1",
            label="paragraph",
            text="Le système utilise une architecture distribuée.",
            sequence=0,
        ),
        SectionElement(
            node_id="img1",
            label="picture",
            text="",
            minio_url="http://minio:9000/documents/images/test/img1_picture.png",
            sequence=1,
        ),
    ]
    markdown = _build_markdown(breadcrumbs, elements, "3.1 Composants")

    assert "[Contexte]" in markdown
    assert "test.pdf" in markdown
    assert "Le système utilise une architecture distribuée." in markdown
    # Chaque élément textuel porte son identifiant citable
    assert "[src:para1]" in markdown
    assert "[img:img1]" in markdown


def test_build_markdown_empty_elements() -> None:
    markdown = _build_markdown([], [], "Section vide")
    assert markdown == ""


def test_build_markdown_code_element() -> None:
    elements = [
        SectionElement(
            node_id="code1",
            label="code",
            text="def hello(): return 'world'",
            sequence=0,
        )
    ]
    markdown = _build_markdown([], elements, "")
    assert "```" in markdown
    assert "def hello()" in markdown
