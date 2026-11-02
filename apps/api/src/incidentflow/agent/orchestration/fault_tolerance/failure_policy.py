"""Classify failures without exposing provider or credential details."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowFailure:
    """A safe summary of a node failure for operators and graph state."""

    code: str
    node: str
    retryable: bool
    message: str


def classify_node_failure(node_name: str, error: BaseException) -> WorkflowFailure:
    """Map a technical exception to a non-sensitive workflow outcome."""
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return WorkflowFailure("EXTERNAL_SOURCE_UNAVAILABLE", node_name, True, "One or more external sources could not be reached.")
    return WorkflowFailure("WORKFLOW_NODE_FAILED", node_name, False, "The investigation could not complete one processing step.")
