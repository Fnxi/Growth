import base64
import binascii
from functools import lru_cache
import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    app_env: Literal["development", "production"]
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
    intelligence_metric_change_threshold_percent: int = Field(default=30, ge=1, le=1000)
    intelligence_check_duration_threshold_percent: int = Field(default=50, ge=1, le=1000)
    intelligence_recurrent_event_threshold: int = Field(default=3, ge=2, le=100)
    security_jwt_active_kid: str | None = None
    security_jwt_keyring: str | None = None
    security_jwt_issuer: str = "growth-hacking-lab"
    security_jwt_audience: str = "growth-hacking-lab-api"
    security_access_token_minutes: int = Field(default=10, ge=1, le=60)
    security_refresh_token_days: int = Field(default=14, ge=1, le=31)
    security_session_max_days: int = Field(default=30, ge=1, le=90)
    security_cors_allowed_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    security_docs_enabled: bool | None = None
    security_cookie_secure: bool | None = None
    security_cookie_samesite: str = "lax"
    security_hsts_enabled: bool = False
    security_auth_rate_limit: int = Field(default=5, ge=1, le=100)
    security_auth_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    security_refresh_rate_limit: int = Field(default=10, ge=1, le=100)
    security_refresh_rate_window_seconds: int = Field(default=60, ge=1, le=3600)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+"):
            raise ValueError("DATABASE_URL must use a PostgreSQL SQLAlchemy dialect.")
        return value

    @field_validator("security_jwt_keyring", mode="before")
    @classmethod
    def validate_keyring_json(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("SECURITY_JWT_KEYRING must be a JSON object string.")
        try:
            parsed = json.loads(value, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, _DuplicateKeyError) as error:
            raise ValueError("SECURITY_JWT_KEYRING must be a JSON object with unique properties.") from error
        if not isinstance(parsed, dict):
            raise ValueError("SECURITY_JWT_KEYRING must be a JSON object.")
        return value

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        keyring = self.jwt_keyring
        if self.security_cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("SECURITY_COOKIE_SAMESITE must be lax, strict, or none.")
        if bool(self.security_jwt_active_kid) != bool(keyring):
            raise ValueError("SECURITY_JWT_ACTIVE_KID and SECURITY_JWT_KEYRING must be configured together.")
        if self.security_jwt_active_kid:
            if not _valid_kid(self.security_jwt_active_kid):
                raise ValueError("SECURITY_JWT_ACTIVE_KID is invalid.")
            if self.security_jwt_active_kid not in keyring:
                raise ValueError("SECURITY_JWT_ACTIVE_KID must identify a key in SECURITY_JWT_KEYRING.")
        for kid, key in keyring.items():
            if not _valid_kid(kid):
                raise ValueError("SECURITY_JWT_KEYRING contains an invalid key id.")
        if any(origin == "*" or "*" in origin or origin.lower() == "null" for origin in self.cors_allowed_origins):
            raise ValueError("SECURITY_CORS_ALLOWED_ORIGINS must contain explicit origins, never wildcards or null.")
        for origin in self.cors_allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError("SECURITY_CORS_ALLOWED_ORIGINS must contain absolute origin URLs only.")
        if self.app_env == "production":
            if not self.security_jwt_active_kid or not keyring:
                raise ValueError("SECURITY_JWT_ACTIVE_KID and SECURITY_JWT_KEYRING are required in production.")
            if not self.cors_allowed_origins:
                raise ValueError("SECURITY_CORS_ALLOWED_ORIGINS is required in production.")
            if self.docs_enabled:
                raise ValueError("OpenAPI documentation must be disabled in production.")
            if not self.cookie_secure:
                raise ValueError("SECURITY_COOKIE_SECURE must be enabled in production.")
            if not self.security_hsts_enabled:
                raise ValueError("SECURITY_HSTS_ENABLED must be enabled in production after HTTPS is guaranteed by deployment.")
        return self

    @property
    def allowed_destination_hosts(self) -> tuple[str, ...]:
        return tuple(host.strip().lower() for host in self.tracking_allowed_destination_hosts.split(",") if host.strip())

    @property
    def cors_allowed_origins(self) -> tuple[str, ...]:
        return tuple(origin.strip().rstrip("/") for origin in self.security_cors_allowed_origins.split(",") if origin.strip())

    @property
    def docs_enabled(self) -> bool:
        return self.app_env == "development" if self.security_docs_enabled is None else self.security_docs_enabled

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production" if self.security_cookie_secure is None else self.security_cookie_secure

    @property
    def jwt_keyring(self) -> dict[str, bytes]:
        if self.security_jwt_keyring is None:
            return {}
        keyring = json.loads(self.security_jwt_keyring, object_pairs_hook=_reject_duplicate_keys)
        return {kid: _decode_signing_key(key) for kid, key in keyring.items()}


def _valid_kid(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value))


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError("Duplicate JSON property.")
        result[key] = value
    return result


def _decode_signing_key(value: object) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Each SECURITY_JWT_KEYRING value must be unpadded Base64URL.")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Each SECURITY_JWT_KEYRING value must be valid Base64URL.") from error
    if len(decoded) < 32 or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise ValueError("Each SECURITY_JWT_KEYRING value must be canonical Base64URL for at least 32 bytes.")
    return decoded


@lru_cache
def get_settings() -> Settings:
    return Settings()
