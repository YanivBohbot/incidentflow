import os
from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from incidentflow.core import ssm
from incidentflow.core.config import Settings, get_settings
from incidentflow.core.ssm import load_ssm_parameters_into_environ
from incidentflow.infrastructure.database import session as session_module


class _FakeSsmClient:
    def __init__(self, pages: list[list[dict[str, str]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get_parameters_by_path(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        index = int(kwargs.get("NextToken", "0"))
        response: dict[str, Any] = {"Parameters": self.pages[index]}
        if index + 1 < len(self.pages):
            response["NextToken"] = str(index + 1)
        return response


def test_ssm_parameters_fill_missing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Work on a copy so keys the loader sets do not leak into other tests.
    monkeypatch.setattr(os, "environ", {"DATABASE_URL": "preset"})
    client = _FakeSsmClient(
        [
            [
                {"Name": "/incidentflow/OPENAI_API_KEY", "Value": "sk-test"},
                {"Name": "/incidentflow/DATABASE_URL", "Value": "from-ssm"},
            ],
            [{"Name": "/incidentflow/PINECONE_API_KEY", "Value": "pc-test"}],
        ]
    )

    names = load_ssm_parameters_into_environ("/incidentflow", client=client)

    assert names == ["OPENAI_API_KEY", "PINECONE_API_KEY"]
    assert os.environ["OPENAI_API_KEY"] == "sk-test"
    assert os.environ["PINECONE_API_KEY"] == "pc-test"
    assert os.environ["DATABASE_URL"] == "preset"
    assert client.calls[0] == {"Path": "/incidentflow", "Recursive": False, "WithDecryption": True}
    assert client.calls[1]["NextToken"] == "1"


def test_ssm_secrets_load_before_settings_when_path_set(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded_paths: list[str] = []

    def fake_loader(path: str) -> list[str]:
        loaded_paths.append(path)
        monkeypatch.setenv("JOB_LEASE_SECONDS", "77")
        return ["JOB_LEASE_SECONDS"]

    get_settings()  # A settings object cached before the secrets arrive must be dropped.
    monkeypatch.setenv(ssm.SSM_PATH_ENV, "/incidentflow")
    monkeypatch.setattr(ssm, "load_ssm_parameters_into_environ", fake_loader)

    assert ssm.load_ssm_secrets_if_configured() == ["JOB_LEASE_SECONDS"]
    assert loaded_paths == ["/incidentflow"]
    assert get_settings().job_lease_seconds == 77


def test_ssm_secrets_skipped_without_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_loader(_path: str) -> list[str]:
        raise AssertionError("SSM must not be read without INCIDENTFLOW_SSM_PATH")

    monkeypatch.delenv(ssm.SSM_PATH_ENV, raising=False)
    monkeypatch.setattr(ssm, "load_ssm_parameters_into_environ", unexpected_loader)

    assert ssm.load_ssm_secrets_if_configured() == []


def test_queue_region_falls_back_to_aws_region(monkeypatch: pytest.MonkeyPatch) -> None:
    base = {"database_url": "sqlite://", "_env_file": None}
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert Settings(**base).queue_region == "us-east-1"
    monkeypatch.setenv("AWS_REGION", "eu-west-3")
    assert Settings(**base).queue_region == "eu-west-3"
    assert Settings(**base, job_queue_region="ap-south-1").queue_region == "ap-south-1"


def _capture_engine_kwargs(monkeypatch: pytest.MonkeyPatch, url: str) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_create_engine(database_url: str, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_NULL_POOL", "true")
    get_settings.cache_clear()
    session_module.get_session_factory.cache_clear()
    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(session_module, "sessionmaker", lambda **kwargs: object())
    session_module.get_session_factory()
    get_settings.cache_clear()
    session_module.get_session_factory.cache_clear()
    return captured


def test_postgres_engine_uses_null_pool_and_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = _capture_engine_kwargs(monkeypatch, "postgresql+psycopg://u:p@host/db")

    assert kwargs["poolclass"] is NullPool
    assert kwargs["connect_args"] == {"connect_timeout": 15, "prepare_threshold": None}


def test_sqlite_engine_has_no_postgres_connect_args(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _capture_engine_kwargs(monkeypatch, "sqlite://")

    assert "connect_args" not in kwargs
