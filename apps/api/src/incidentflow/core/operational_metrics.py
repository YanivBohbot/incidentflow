"""Small in-process operational counters exposed for local monitoring."""

from collections import Counter
from threading import Lock


class OperationalMetrics:
    """Collect bounded, non-sensitive counters for API health."""

    def __init__(self) -> None:
        """Initialize counters guarded for concurrent FastAPI requests."""
        self._lock = Lock()
        self._request_statuses: Counter[str] = Counter()

    def record_request(self, status_code: int) -> None:
        """Increment the HTTP response counter for one completed request."""
        with self._lock:
            self._request_statuses[str(status_code)] += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        """Return copies suitable for a JSON monitoring endpoint."""
        with self._lock:
            return {"requests_by_status": dict(self._request_statuses)}
