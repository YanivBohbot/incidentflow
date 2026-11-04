import os

import pytest

from incidentflow.core.config import get_settings

# Required settings get placeholder values so the suite runs without a .env (CI). Tests never
# reach OpenAI or PostgreSQL: they use fakes, in-memory SQLite and InMemorySaver.
_REQUIRED_PLACEHOLDERS = {
    "OPENAI_API_KEY": "test-openai-key",
    "DATABASE_URL": "sqlite://",
}


@pytest.fixture(autouse=True)
def _required_settings(monkeypatch: pytest.MonkeyPatch):
    for name, value in _REQUIRED_PLACEHOLDERS.items():
        if name not in os.environ:
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
