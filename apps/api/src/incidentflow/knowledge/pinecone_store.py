"""Read-only Pinecone retrieval and explicit document indexing helpers."""

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone

from incidentflow.core.config import Settings


def split_documents(documents: list[Document]) -> list[Document]:
    """Split documents without losing their source, title, and character offset metadata."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        add_start_index=True,
    )
    return splitter.split_documents(documents)


def chunk_ids(documents: list[Document]) -> list[str]:
    """Create stable IDs so re-ingestion updates existing chunks instead of duplicating them."""
    return [
        sha256(
            (
                f"{document.metadata.get('source_url') or document.metadata.get('source_path') or document.metadata.get('document_id', '')}:"
                f"{document.metadata.get('start_index', 0)}:{document.page_content}"
            ).encode()
        ).hexdigest()
        for document in documents
    ]


class PineconeKnowledgeStore:
    """Pinecone store used by ingestion and the read-only Knowledge Agent."""

    def __init__(
        self,
        vector_stores: dict[str, PineconeVectorStore],
        index: Any,
        namespaces: tuple[str, ...],
        top_k: int,
        candidate_k: int | None = None,
        min_score: float = 0.0,
    ) -> None:
        self._vector_stores = vector_stores
        self._index = index
        self._namespaces = namespaces
        self._top_k = top_k
        self._candidate_k = max(candidate_k or top_k, top_k)
        self._min_score = min_score

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        namespaces: tuple[str, ...] | None = None,
    ) -> "PineconeKnowledgeStore":
        if not settings.pinecone_api_key:
            raise RuntimeError("Set PINECONE_API_KEY before using the Pinecone knowledge store.")

        selected_namespaces = tuple(
            dict.fromkeys(namespace.strip() for namespace in namespaces if namespace.strip())
            if namespaces is not None
            else (settings.pinecone_namespace, settings.pinecone_local_namespace)
        )
        if not selected_namespaces:
            raise RuntimeError("Configure at least one Pinecone namespace.")

        client = Pinecone(api_key=settings.pinecone_api_key)
        index = client.Index(settings.pinecone_index_name)
        embeddings = OpenAIEmbeddings(
            model=settings.pinecone_embedding_model,
            api_key=settings.openai_api_key,
        )
        vector_stores = {
            namespace: PineconeVectorStore(
                embedding=embeddings,
                index=index,
                namespace=namespace,
            )
            for namespace in selected_namespaces
        }
        return cls(
            vector_stores=vector_stores,
            index=index,
            namespaces=selected_namespaces,
            top_k=settings.pinecone_top_k,
            candidate_k=settings.pinecone_candidate_k,
            min_score=settings.pinecone_min_score,
        )

    def search(
        self,
        query: str,
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> list[tuple[Document, float]]:
        """Merge filtered, sufficiently relevant chunks from the configured namespaces."""
        matches: list[tuple[Document, float]] = []
        for namespace, vector_store in self._vector_stores.items():
            namespace_matches = vector_store.similarity_search_with_score(
                query,
                k=self._candidate_k,
                filter=metadata_filter,
            )
            for document, score in namespace_matches:
                if score < self._min_score:
                    continue
                document.metadata["knowledge_namespace"] = namespace
                matches.append((document, score))
        return sorted(matches, key=lambda match: match[1], reverse=True)[: self._top_k]

    @property
    def top_k(self) -> int:
        """Return the number of results exposed to the Knowledge Agent."""
        return self._top_k

    def add_documents(self, documents: list[Document]) -> list[str]:
        """Explicit ingestion-only write operation; never called by the runtime agent."""
        ids = chunk_ids(documents)
        return self._vector_stores[self._namespaces[0]].add_documents(documents=documents, ids=ids)

    def replace_documents(self, documents: list[Document]) -> list[str]:
        """Replace only this store's configured namespace with a fresh document set."""
        namespace = self._namespaces[0]
        stats = self._index.describe_index_stats()
        if namespace in stats.namespaces:
            self._index.delete(delete_all=True, namespace=namespace)
        return self.add_documents(documents)
