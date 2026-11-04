from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from incidentflow.core.config import get_settings


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create the engine on first use, not at import, so importing the API needs no settings."""
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def SessionLocal() -> Session:
    """Open a session; named like the sessionmaker it replaces so call sites stay unchanged."""
    return get_session_factory()()


def get_db_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
