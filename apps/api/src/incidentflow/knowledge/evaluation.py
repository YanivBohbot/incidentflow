"""Small, deterministic retrieval metrics for IncidentFlow's curated evaluation cases."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from langchain_core.documents import Document


@dataclass(frozen=True)
class RetrievalEvaluationCase:
    name: str
    query: str
    expected_metadata: Mapping[str, str]


@dataclass(frozen=True)
class RetrievalEvaluationResult:
    name: str
    rank: int | None


def evaluate_retrieval_cases(
    cases: list[RetrievalEvaluationCase],
    search: Callable[[str], list[tuple[Document, float]]],
) -> list[RetrievalEvaluationResult]:
    """Return the one-based rank of each expected source, or None when it was not retrieved."""
    results: list[RetrievalEvaluationResult] = []
    for case in cases:
        rank = next(
            (
                position
                for position, (document, _) in enumerate(search(case.query), start=1)
                if all(
                    document.metadata.get(key) == expected
                    for key, expected in case.expected_metadata.items()
                )
            ),
            None,
        )
        results.append(RetrievalEvaluationResult(name=case.name, rank=rank))
    return results


def recall_at_k(results: list[RetrievalEvaluationResult]) -> float:
    """Measure the fraction of cases whose expected source appeared in the top-k results."""
    if not results:
        return 0.0
    return sum(result.rank is not None for result in results) / len(results)


def mean_reciprocal_rank(results: list[RetrievalEvaluationResult]) -> float:
    """Reward evaluation cases whose expected source appears earlier in the ranking."""
    if not results:
        return 0.0
    return sum(1 / result.rank if result.rank else 0 for result in results) / len(results)
