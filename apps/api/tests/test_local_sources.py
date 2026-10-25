from langchain_core.documents import Document

from incidentflow.knowledge import local_sources


def test_load_local_markdown_and_text_sources_preserves_metadata(tmp_path) -> None:
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    (source_dir / "payment-api.md").write_text(
        "# Payment API\n\nInvestigate database timeouts before changing configuration.",
        encoding="utf-8",
    )
    (source_dir / "database.txt").write_text(
        "Record connection saturation metrics during an incident.",
        encoding="utf-8",
    )

    documents = local_sources.load_local_knowledge_sources(source_dir)

    assert len(documents) == 2
    assert {document.metadata["source_kind"] for document in documents} == {
        "local_markdown",
        "local_text",
    }
    assert {document.metadata["source_path"] for document in documents} == {
        "database.txt",
        "payment-api.md",
    }
    assert all(document.metadata["document_id"].startswith("LOCAL-") for document in documents)


def test_load_local_pdf_preserves_one_based_page_number(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    pdf_path = source_dir / "database-guide.pdf"
    pdf_path.touch()

    class FakePdfLoader:
        def __init__(self, path: str) -> None:
            assert path == str(pdf_path)

        def load(self) -> list[Document]:
            return [Document(page_content="Connection pool guidance.", metadata={"page": 0})]

    monkeypatch.setattr(local_sources, "PyPDFLoader", FakePdfLoader)

    documents = local_sources.load_local_knowledge_sources(source_dir)

    assert documents[0].metadata["source_kind"] == "local_pdf"
    assert documents[0].metadata["source_path"] == "database-guide.pdf"
    assert documents[0].metadata["page_number"] == 1
