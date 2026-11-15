"""Queue abstraction for investigation jobs (at-least-once delivery)."""

from collections import deque
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ReceivedJob:
    investigation_id: UUID
    receipt: str


class JobQueue(Protocol):
    def send(self, investigation_id: UUID) -> None: ...

    def receive(self, *, max_messages: int, wait_seconds: int) -> list[ReceivedJob]: ...

    def ack(self, job: ReceivedJob) -> None: ...

    def extend(self, job: ReceivedJob, *, visibility_seconds: int) -> None: ...


class InMemoryJobQueue:
    """Non-blocking FIFO queue for tests."""

    def __init__(self) -> None:
        self.sent: list[UUID] = []
        self.acked: list[ReceivedJob] = []
        self.extended: list[tuple[ReceivedJob, int]] = []
        self._pending: deque[UUID] = deque()

    def send(self, investigation_id: UUID) -> None:
        self.sent.append(investigation_id)
        self._pending.append(investigation_id)

    def receive(self, *, max_messages: int, wait_seconds: int) -> list[ReceivedJob]:
        jobs: list[ReceivedJob] = []
        while self._pending and len(jobs) < max_messages:
            investigation_id = self._pending.popleft()
            jobs.append(
                ReceivedJob(investigation_id=investigation_id, receipt=str(investigation_id))
            )
        return jobs

    def ack(self, job: ReceivedJob) -> None:
        self.acked.append(job)

    def extend(self, job: ReceivedJob, *, visibility_seconds: int) -> None:
        self.extended.append((job, visibility_seconds))
