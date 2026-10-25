from langchain_core.documents import Document

from incidentflow.knowledge.evaluation import (
    RetrievalEvaluationCase,
    evaluate_retrieval_cases,
    mean_reciprocal_rank,
    recall_at_k,
)


def test_retrieval_evaluation_calculates_recall_and_mrr() -> None:
    cases = [
        RetrievalEvaluationCase("first", "query 1", {"document_id": "A"}),
        RetrievalEvaluationCase("second", "query 2", {"document_id": "B"}),
    ]
    documents = {
        "query 1": [
            (Document(page_content="wrong", metadata={"document_id": "X"}), 0.9),
            (Document(page_content="right", metadata={"document_id": "A"}), 0.8),
        ],
        "query 2": [(Document(page_content="right", metadata={"document_id": "B"}), 0.9)],
    }

    results = evaluate_retrieval_cases(cases, lambda query: documents[query])

    assert [result.rank for result in results] == [2, 1]
    assert recall_at_k(results) == 1.0
    assert mean_reciprocal_rank(results) == 0.75
