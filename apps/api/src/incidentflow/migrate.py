"""One-shot schema setup: Alembic migrations, then LangGraph's checkpoint tables.

Run once per deploy (``python -m incidentflow.migrate``) instead of at every API or worker
start, so many instances never race to create the same tables.
"""

import asyncio
import os
import sys

from alembic.config import Config

from alembic import command
from incidentflow.agent.orchestration.checkpoints.postgres import open_postgres_checkpointer
from incidentflow.core.config import get_settings

DEFAULT_ALEMBIC_CONFIG = "alembic.ini"


async def _setup_checkpointer(database_url: str) -> None:
    async with open_postgres_checkpointer(database_url) as checkpointer:
        await checkpointer.setup()


def run_migrations() -> None:
    """Apply ``alembic upgrade head``, then create or upgrade the checkpoint tables."""
    config = Config(os.environ.get("ALEMBIC_CONFIG", DEFAULT_ALEMBIC_CONFIG))
    command.upgrade(config, "head")
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(
        _setup_checkpointer(get_settings().checkpoint_database_url), loop_factory=loop_factory
    )


if __name__ == "__main__":
    run_migrations()
