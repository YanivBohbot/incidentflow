"""Safe, provider-neutral classification for workflow node failures."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowFailure:
    """A public-safe summary used for graph state and operator-facing reports."""

    code: str
    node: str
    retryable: bool
    message: str


def classify_node_failure(node_name: str, error: BaseException) -> WorkflowFailure:
    """Classify an exception without copying provider details into durable state."""
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return WorkflowFailure(
            code="EXTERNAL_SOURCE_UNAVAILABLE",
            node=node_name,
            retryable=True,
            message="One or more external sources could not be reached.",
        )
    return WorkflowFailure(
        code="WORKFLOW_NODE_FAILED",
        node=node_name,
        retryable=False,
        message="The investigation could not complete one processing step.",
    )
