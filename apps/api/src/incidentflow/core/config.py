from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IncidentFlow API"
    environment: str = "development"
    api_prefix: str = "/api"
    openai_api_key: str
    openai_model: str = "gpt-4.1-mini"
    # PostgreSQL
    database_url: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
