"""Asynchronous PostgreSQL checkpoint persistence for LangGraph workflows."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

# A pool, not one long-lived connection: Neon suspends idle compute and Lambda freezes warm
# environments, so a cached connection is often dead on the next use. The pool checks each
# connection before handing it out and replaces broken ones.
CHECKPOINT_POOL_MAX_SIZE = 5
# Hold no idle connections (they would keep Neon awake) and close spare ones quickly.
CHECKPOINT_POOL_MIN_SIZE = 0
CHECKPOINT_POOL_MAX_IDLE_SECONDS = 60.0


def normalize_checkpoint_database_url(database_url: str) -> str:
    """Convert the SQLAlchemy PostgreSQL URL into the driver-neutral saver URL."""
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if database_url.startswith("postgresql://"):
        return database_url
    raise ValueError("LangGraph checkpoints require a PostgreSQL database URL.")


@asynccontextmanager
async def _open_postgres_saver(database_url: str) -> AsyncIterator[Any]:
    """Open LangGraph's asynchronous PostgreSQL saver over a checked connection pool."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        database_url,
        min_size=CHECKPOINT_POOL_MIN_SIZE,
        max_size=CHECKPOINT_POOL_MAX_SIZE,
        max_idle=CHECKPOINT_POOL_MAX_IDLE_SECONDS,
        check=AsyncConnectionPool.check_connection,
        # The settings AsyncPostgresSaver.from_conn_string uses; setup() needs autocommit.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    try:
        yield AsyncPostgresSaver(conn=pool)
    finally:
        await pool.close()


def open_postgres_checkpointer(database_url: str) -> Any:
    """Return an async saver context using the normalized PostgreSQL connection URL."""
    return _open_postgres_saver(normalize_checkpoint_database_url(database_url))
