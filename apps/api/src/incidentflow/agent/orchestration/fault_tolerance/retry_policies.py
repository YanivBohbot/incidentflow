"""Bounded retry rules for idempotent external reads only."""

from langgraph.types import RetryPolicy


def external_read_retry_policy() -> RetryPolicy:
    """Retry transient read failures once; never use this policy for writes."""
    return RetryPolicy(
        max_attempts=2,
        initial_interval=0.0,
        jitter=False,
        retry_on=(ConnectionError, TimeoutError, OSError),
    )
