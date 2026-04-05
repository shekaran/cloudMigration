"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global application settings — sourced from .env or environment."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Application
    app_env: str = "development"
    app_debug: bool = False
    app_log_level: str = "INFO"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1

    # Observability
    log_format: str = "json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
