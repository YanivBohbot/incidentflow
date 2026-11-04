import importlib
import sys

from incidentflow.core.config import get_settings


def test_importing_routes_needs_no_database_or_openai_settings(monkeypatch, tmp_path) -> None:
    """CI has no .env: importing the API must not read settings or open a database engine."""
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    for name in [
        m for m in sys.modules if m.startswith("incidentflow.infrastructure.database.session")
    ]:
        monkeypatch.delitem(sys.modules, name)
    try:
        session = importlib.import_module("incidentflow.infrastructure.database.session")
        assert callable(session.SessionLocal)
    finally:
        get_settings.cache_clear()


def test_session_factory_uses_the_configured_database(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    from incidentflow.infrastructure.database import session

    session.get_session_factory.cache_clear()
    try:
        with session.SessionLocal() as db:
            assert db.get_bind().url.drivername == "sqlite"
    finally:
        session.get_session_factory.cache_clear()
        get_settings.cache_clear()
