from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from incidentflow.core.config import get_settings


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create the engine on first use, not at import, so importing the API needs no settings."""
    settings = get_settings()
    options: dict[str, Any] = {"pool_pre_ping": True}
    if settings.database_null_pool:
        options["poolclass"] = NullPool
    if make_url(settings.database_url).get_backend_name() == "postgresql":
        # prepare_threshold=None disables prepared statements, which pooled Neon rejects.
        options["connect_args"] = {
            "connect_timeout": settings.database_connect_timeout_seconds,
            "prepare_threshold": None,
        }
    engine = create_engine(settings.database_url, **options)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def SessionLocal() -> Session:
    """Open a session; named like the sessionmaker it replaces so call sites stay unchanged."""
    return get_session_factory()()


def get_db_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
