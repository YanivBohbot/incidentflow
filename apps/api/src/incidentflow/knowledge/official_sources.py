"""Official public sources used for the first IncidentFlow RAG validation."""

import os

os.environ.setdefault("USER_AGENT", "IncidentFlow/0.1 public-knowledge-ingestion")

from dataclasses import dataclass

from bs4 import SoupStrainer
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document


@dataclass(frozen=True)
class OfficialKnowledgeSource:
    """A public document whose origin is retained in every Pinecone chunk."""

    document_id: str
    title: str
    url: str


OFFICIAL_KNOWLEDGE_SOURCES = (
    OfficialKnowledgeSource(
        document_id="MONGODB-CONNECTION-POOL-OVERVIEW",
        title="MongoDB Connection Pool Overview",
        url="https://www.mongodb.com/docs/v8.3/administration/connection-pool-overview/",
    ),
    OfficialKnowledgeSource(
        document_id="MONGODB-CONNECTION-POOL-PERFORMANCE",
        title="MongoDB Performance: Number of Connections",
        url="https://www.mongodb.com/docs/manual/administration/analyzing-mongodb-performance/",
    ),
    OfficialKnowledgeSource(
        document_id="MONGODB-NODE-CONNECTION-POOLS",
        title="MongoDB Node.js Driver: Manage Connections with Connection Pools",
        url="https://www.mongodb.com/docs/drivers/node/current/connect/connection-options/connection-pools/",
    ),
)


def main_content_soup_strainer() -> SoupStrainer:
    """Keep only the semantic main region, excluding site navigation and footers."""
    return SoupStrainer("main")


def remove_leading_page_chrome(page_content: str) -> str:
    """Drop a leading breadcrumb/title control while retaining article content and metadata."""
    marker = "Copy page"
    marker_position = page_content.find(marker)
    if page_content.lstrip().startswith("Docs Home") and 0 <= marker_position <= 500:
        return page_content[marker_position + len(marker) :].lstrip()
    return page_content


def load_official_knowledge_sources() -> list[Document]:
    """Load current official web pages while retaining stable source metadata."""
    source_by_url = {source.url: source for source in OFFICIAL_KNOWLEDGE_SOURCES}
    loader = WebBaseLoader(
        web_paths=list(source_by_url),
        bs_kwargs={"parse_only": main_content_soup_strainer()},
    )
    documents = loader.load()

    for document in documents:
        document.page_content = remove_leading_page_chrome(document.page_content)
        source_url = str(document.metadata.get("source", ""))
        source = source_by_url.get(source_url)
        if source is None:
            raise RuntimeError(
                f"Loaded a document not present in the source manifest: {source_url}"
            )
        document.metadata.update(
            {
                "document_id": source.document_id,
                "title": source.title,
                "source_url": source.url,
                "source_kind": "official_public_documentation",
                "document_version": "web-current",
            }
        )

    return documents
