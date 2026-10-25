from langchain_core.documents import Document

from incidentflow.knowledge.pinecone_store import PineconeKnowledgeStore, chunk_ids, split_documents


def test_document_splitting_retains_source_metadata() -> None:
    document = Document(
        page_content="Connection pool guidance. " * 100,
        metadata={
            "document_id": "MONGODB-CONNECTION-POOL-OVERVIEW",
            "source_url": "https://docs.example.test/pools",
            "title": "Connection Pool Overview",
        },
    )

    chunks = split_documents([document])

    assert len(chunks) > 1
    assert all(
        chunk.metadata["document_id"] == document.metadata["document_id"] for chunk in chunks
    )
    assert all("start_index" in chunk.metadata for chunk in chunks)


def test_chunk_ids_are_stable_and_distinct() -> None:
    documents = [
        Document(page_content="first", metadata={"source_url": "https://docs.example.test/one"}),
        Document(page_content="second", metadata={"source_url": "https://docs.example.test/one"}),
    ]

    first_ids = chunk_ids(documents)

    assert first_ids == chunk_ids(documents)
    assert len(set(first_ids)) == len(documents)


def test_chunk_ids_include_a_local_source_path() -> None:
    documents = [
        Document(page_content="first", metadata={"source_path": "guides/payment.md"}),
        Document(page_content="first", metadata={"source_path": "guides/database.md"}),
    ]

    assert len(set(chunk_ids(documents))) == len(documents)


class _FakeVectorStore:
    def __init__(self, matches: list[tuple[Document, float]]) -> None:
        self._matches = matches
        self.last_filter = None

    def similarity_search_with_score(
        self,
        query: str,
        k: int,
        filter=None,
    ) -> list[tuple[Document, float]]:
        self.last_filter = filter
        return self._matches[:k]

    def add_documents(self, documents: list[Document], ids: list[str]) -> list[str]:
        return ids


class _FakeIndex:
    def __init__(self, namespaces: dict[str, object]) -> None:
        self._namespaces = namespaces
        self.deleted_namespaces: list[str] = []

    def describe_index_stats(self):
        return type("Stats", (), {"namespaces": self._namespaces})()

    def delete(self, *, delete_all: bool, namespace: str) -> None:
        assert delete_all is True
        self.deleted_namespaces.append(namespace)


def test_search_merges_and_ranks_multiple_namespaces() -> None:
    public_document = Document(page_content="public", metadata={})
    local_document = Document(page_content="local", metadata={})
    store = PineconeKnowledgeStore(
        vector_stores={
            "official-public-docs": _FakeVectorStore([(public_document, 0.4)]),
            "local-incident-documents": _FakeVectorStore([(local_document, 0.9)]),
        },
        index=object(),
        namespaces=("official-public-docs", "local-incident-documents"),
        top_k=2,
    )

    results = store.search("connection timeout")

    assert [document.page_content for document, _ in results] == ["local", "public"]
    assert results[0][0].metadata["knowledge_namespace"] == "local-incident-documents"


def test_replace_documents_skips_delete_when_namespace_does_not_exist() -> None:
    vector_store = _FakeVectorStore([])
    index = _FakeIndex(namespaces={})
    store = PineconeKnowledgeStore(
        vector_stores={"local-incident-documents": vector_store},
        index=index,
        namespaces=("local-incident-documents",),
        top_k=3,
    )

    ids = store.replace_documents(
        [Document(page_content="guide", metadata={"document_id": "LOCAL"})]
    )

    assert len(ids) == 1
    assert index.deleted_namespaces == []


def test_search_applies_filters_and_discards_low_scoring_matches() -> None:
    high_score_document = Document(page_content="high", metadata={})
    low_score_document = Document(page_content="low", metadata={})
    vector_store = _FakeVectorStore([(high_score_document, 0.8), (low_score_document, 0.1)])
    store = PineconeKnowledgeStore(
        vector_stores={"local-incident-documents": vector_store},
        index=object(),
        namespaces=("local-incident-documents",),
        top_k=3,
        candidate_k=8,
        min_score=0.2,
    )

    results = store.search("recovery", metadata_filter={"source_kind": "local_pdf"})

    assert [document.page_content for document, _ in results] == ["high"]
    assert vector_store.last_filter == {"source_kind": "local_pdf"}
