"""Clean up investigations left RUNNING by an API process that stopped mid-run."""

import logging

from sqlalchemy.orm import Session, sessionmaker

from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)

logger = logging.getLogger(__name__)

INTERRUPTED_RUN_MESSAGE = (
    "The API restarted while this investigation was running, so it never finished. "
    "Launch a new investigation for the incident."
)


def recover_interrupted_investigations(session_factory: sessionmaker[Session]) -> int:
    """Fail every RUNNING investigation at startup.

    An investigation runs inside one API request. When the process starts, no request can be in
    flight, so a RUNNING row can only come from a previous process that stopped (restart, crash,
    deploy). This assumes a single API instance; several instances would need a heartbeat or
    lease instead.
    """
    with session_factory() as session:
        count = InvestigationRepository(session).fail_running_investigations(
            INTERRUPTED_RUN_MESSAGE
        )
    if count:
        logger.warning("Marked %d interrupted investigation(s) as FAILED at startup", count)
    return count
