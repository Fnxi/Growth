from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    tracking_base_url: str = "http://127.0.0.1:8000"
    tracking_allowed_destination_hosts: str = "instagram.com,www.instagram.com"
    tracking_rate_limit: int = 30
    tracking_rate_window_seconds: int = 60
    system_check_token: str | None = None
    monitoring_scheduler_enabled: bool = False
    monitoring_check_interval_seconds: int = Field(default=60, ge=10, le=86400)
    ai_enabled: bool = False
    ai_provider: str = "openai"
    ai_openai_api_key: str | None = None
    ai_model: str = "gpt-4.1-mini"
    ai_timeout_seconds: int = Field(default=20, ge=1, le=120)
    ai_max_output_tokens: int = Field(default=700, ge=100, le=4000)
    ai_max_context_characters: int = Field(default=12000, ge=1000, le=50000)
    ai_rate_limit: int = Field(default=10, ge=1, le=1000)
    ai_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    ai_max_concurrent_requests: int = Field(default=2, ge=1, le=20)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+"):
            raise ValueError("DATABASE_URL must use a PostgreSQL SQLAlchemy dialect.")
        return value

    @property
    def allowed_destination_hosts(self) -> tuple[str, ...]:
        return tuple(host.strip().lower() for host in self.tracking_allowed_destination_hosts.split(",") if host.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
