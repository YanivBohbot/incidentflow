from typing import Any


def normalize_checkpoint_database_url(database_url: str) -> str:
    """Convert the SQLAlchemy PostgreSQL URL into the driver-neutral saver URL."""
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if database_url.startswith("postgresql://"):
        return database_url
    raise ValueError("LangGraph checkpoints require a PostgreSQL database URL.")


def _open_postgres_saver(database_url: str) -> Any:
    """Open LangGraph's synchronous PostgreSQL saver context on demand."""
    from langgraph.checkpoint.postgres import PostgresSaver

    return PostgresSaver.from_conn_string(database_url)


def open_postgres_checkpointer(database_url: str) -> Any:
    """Return a saver context using the normalized PostgreSQL connection URL."""
    return _open_postgres_saver(normalize_checkpoint_database_url(database_url))
