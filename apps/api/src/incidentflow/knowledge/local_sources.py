"""Load locally supplied PDF, Markdown, and text knowledge sources for IncidentFlow."""

from hashlib import sha256
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

_SUPPORTED_SOURCE_KINDS = {
    ".md": "local_markdown",
    ".pdf": "local_pdf",
    ".txt": "local_text",
}


def _document_id(relative_path: Path) -> str:
    return f"LOCAL-{sha256(relative_path.as_posix().encode()).hexdigest()[:16].upper()}"


def _load_file(path: Path) -> list[Document]:
    if path.suffix.lower() == ".pdf":
        return PyPDFLoader(str(path)).load()
    return TextLoader(str(path), encoding="utf-8", autodetect_encoding=True).load()


def load_local_knowledge_sources(source_dir: Path) -> list[Document]:
    """Load supported local sources and normalize stable, citation-ready metadata."""
    if not source_dir.is_dir():
        raise RuntimeError(f"Knowledge source directory does not exist: {source_dir}")

    documents: list[Document] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SOURCE_KINDS:
            continue

        relative_path = path.relative_to(source_dir)
        source_kind = _SUPPORTED_SOURCE_KINDS[path.suffix.lower()]
        document_version = sha256(path.read_bytes()).hexdigest()
        for document in _load_file(path):
            if not document.page_content.strip():
                continue

            metadata = {
                "document_id": _document_id(relative_path),
                "title": path.stem,
                "source_path": relative_path.as_posix(),
                "source_kind": source_kind,
                "document_version": document_version,
            }
            if "page" in document.metadata:
                metadata["page_number"] = int(document.metadata["page"]) + 1
            document.metadata.update(metadata)
            documents.append(document)

    return documents
