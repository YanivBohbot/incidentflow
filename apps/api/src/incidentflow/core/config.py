import os
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IncidentFlow API"
    environment: str = "development"
    api_prefix: str = "/api"
    auth_enabled: bool = False
    keycloak_issuer_url: str = "http://localhost:8080/realms/incidentflow"
    keycloak_audience: str = "incidentflow-api"
    openai_api_key: SecretStr
    openai_model: str = "gpt-4.1-mini"
    openai_timeout_seconds: float = 60
    langsmith_tracing: bool = False
    langsmith_project: str = "incidentflow-development"
    langsmith_api_key: str | None = None
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    jira_mcp_url: str = "https://mcp.atlassian.com/v2/mcp?tools=all"
    jira_mcp_enabled: bool = False
    jira_mcp_write_enabled: bool = False
    mcp_oauth_token_store_dir: str | None = None
    mcp_oauth_storage_encryption_key: str | None = None
    github_mcp_transport: Literal["http", "stdio"] = "stdio"
    github_mcp_url: str | None = None
    github_mcp_command: str = "docker.exe" if os.name == "nt" else "docker"
    github_mcp_command_args: str = (
        "run,-i,--rm,-p,127.0.0.1:8085:8085,-e,GITHUB_OAUTH_CALLBACK_PORT=8085,"
        "-e,GITHUB_READ_ONLY=1,ghcr.io/github/github-mcp-server"
    )
    github_mcp_enabled: bool = False
    github_mcp_repositories: str = ""
    github_personal_access_token: str | None = None
    cloudwatch_mcp_enabled: bool = False
    cloudwatch_mcp_command: str = "uv"
    cloudwatch_mcp_command_args: str = "tool,run,--from,awslabs.cloudwatch-mcp-server@0.3.1," + (
        "awslabs.cloudwatch-mcp-server.exe" if os.name == "nt" else "awslabs.cloudwatch-mcp-server"
    )
    # Leave the profile empty in AWS deployments so the server uses the attached IAM role.
    cloudwatch_mcp_aws_profile: str | None = None
    cloudwatch_mcp_aws_region: str = "us-east-1"
    cloudwatch_mcp_timeout_seconds: float = 90
    cloudwatch_mcp_log_groups: str = ""
    cloudwatch_mcp_lookback_minutes: int = 60
    mongodb_mcp_url: str = "http://127.0.0.1:3000/mcp"
    mongodb_mcp_enabled: bool = False
    mongodb_mcp_connection_string: str = "mongodb://127.0.0.1:27017/?directConnection=true"
    mongodb_mcp_database: str = "incidentflow_dev"
    mongodb_mcp_events_collection: str = "operational_events"
    pinecone_api_key: str | None = None
    pinecone_enabled: bool = False
    pinecone_index_name: str = "incidentflow-runbooks"
    pinecone_namespace: str = "official-public-docs"
    pinecone_local_namespace: str = "local-incident-documents"
    pinecone_resolved_incidents_enabled: bool = False
    pinecone_resolved_incidents_namespace: str = "resolved_incidents"
    pinecone_embedding_model: str = "text-embedding-3-small"
    pinecone_top_k: int = 3
    pinecone_candidate_k: int = 8
    pinecone_min_score: float = 0.2
    # PostgreSQL
    database_url: str
    langgraph_checkpoint_database_url: str | None = None

    @property
    def checkpoint_database_url(self) -> str:
        """Use a dedicated checkpoint database only when explicitly configured."""
        return self.langgraph_checkpoint_database_url or self.database_url

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def github_mcp_allowed_repositories(self) -> tuple[str, ...]:
        """Return the configured comma-separated repository allowlist."""
        return tuple(
            repository.strip()
            for repository in self.github_mcp_repositories.split(",")
            if repository.strip()
        )

    @property
    def github_mcp_stdio_arguments(self) -> tuple[str, ...]:
        """Return the configured comma-separated Docker command arguments."""
        return tuple(
            argument.strip()
            for argument in self.github_mcp_command_args.split(",")
            if argument.strip()
        )

    @property
    def github_mcp_is_configured(self) -> bool:
        if self.github_mcp_transport == "http":
            return bool(self.github_mcp_url)
        return bool(self.github_mcp_command and self.github_mcp_stdio_arguments)

    @property
    def cloudwatch_mcp_allowed_log_groups(self) -> tuple[str, ...]:
        """Return the comma-separated log groups the CloudWatch agent may query."""
        return tuple(
            log_group.strip()
            for log_group in self.cloudwatch_mcp_log_groups.split(",")
            if log_group.strip()
        )

    @property
    def cloudwatch_mcp_stdio_arguments(self) -> tuple[str, ...]:
        """Return the comma-separated CloudWatch MCP command arguments."""
        return tuple(
            argument.strip()
            for argument in self.cloudwatch_mcp_command_args.split(",")
            if argument.strip()
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    return settings
