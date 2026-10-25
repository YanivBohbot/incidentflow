"""Evaluate real IncidentFlow Pinecone retrieval against a small curated baseline."""

from incidentflow.core.config import get_settings
from incidentflow.knowledge.evaluation import (
    RetrievalEvaluationCase,
    evaluate_retrieval_cases,
    mean_reciprocal_rank,
    recall_at_k,
)
from incidentflow.knowledge.pinecone_store import PineconeKnowledgeStore

EVALUATION_CASES = [
    RetrievalEvaluationCase(
        name="recovery-communications",
        query="What should a cybersecurity recovery communications plan address?",
        expected_metadata={
            "knowledge_namespace": "local-incident-documents",
            "title": "nist-sp-800-184",
        },
    ),
    RetrievalEvaluationCase(
        name="risk-management-integration",
        query="How should incident response be incorporated into cybersecurity risk management?",
        expected_metadata={
            "knowledge_namespace": "local-incident-documents",
            "title": "nist-sp-800-61r3",
        },
    ),
    RetrievalEvaluationCase(
        name="recovery-plan-testing",
        query="How should an organization test and improve a cyber event recovery plan?",
        expected_metadata={
            "knowledge_namespace": "local-incident-documents",
            "title": "nist-sp-800-184",
        },
    ),
    RetrievalEvaluationCase(
        name="incident-roles",
        query="Which organizational roles should participate in incident response and recovery?",
        expected_metadata={
            "knowledge_namespace": "local-incident-documents",
            "title": "nist-sp-800-61r3",
        },
    ),
    RetrievalEvaluationCase(
        name="mongodb-connection-pool",
        query="How should a MongoDB connection pool exhaustion be investigated?",
        expected_metadata={
            "knowledge_namespace": "official-public-docs",
            "document_id": "MONGODB-CONNECTION-POOL-OVERVIEW",
        },
    ),
    RetrievalEvaluationCase(
        name="mongodb-pool-configuration",
        query="Which MongoDB connection pool settings can reduce connection timeout risk?",
        expected_metadata={
            "knowledge_namespace": "official-public-docs",
            "document_id": "MONGODB-NODE-CONNECTION-POOLS",
        },
    ),
    RetrievalEvaluationCase(
        name="mongodb-connection-metrics",
        query="Which MongoDB metrics show current and available database connections?",
        expected_metadata={
            "knowledge_namespace": "official-public-docs",
            "document_id": "MONGODB-CONNECTION-POOL-PERFORMANCE",
        },
    ),
]


def main() -> int:
    store = PineconeKnowledgeStore.from_settings(get_settings())
    results = evaluate_retrieval_cases(EVALUATION_CASES, store.search)
    for result in results:
        print(f"{result.name}: rank={result.rank}")
    print(f"Recall@{store.top_k}: {recall_at_k(results):.2f}")
    print(f"MRR: {mean_reciprocal_rank(results):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
