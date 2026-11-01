import base64
from datetime import datetime, timezone
import json
import secrets

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.security.crypto import MAX_PASSWORD_BYTES, TokenValidationError, hash_password, password_needs_rehash, sign_access_token, validate_access_token, verify_password


def settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+psycopg://user:password@localhost:5432/test",
        "app_env": "development",
        "security_jwt_active_kid": "current",
        "security_jwt_keyring": keyring(current=encoded_key(b"c" * 32)),
        "security_cors_allowed_origins": "http://localhost:8501",
    }
    values.update(overrides)
    return Settings(**values)


def encoded_key(raw: bytes | None = None) -> str:
    return base64.urlsafe_b64encode(raw or secrets.token_bytes(32)).decode("ascii").rstrip("=")


def keyring(**keys: str) -> str:
    return json.dumps(keys)


def test_argon2id_hashing_verifies_only_the_correct_password() -> None:
    password_hash = hash_password("correct horse battery staple")
    assert password_hash.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)
    assert not verify_password("x" * (MAX_PASSWORD_BYTES + 1), password_hash)
    assert not verify_password("password", "not-a-hash")
    assert not password_needs_rehash("not-a-hash")


def test_jwt_validates_access_claims_and_key_rotation() -> None:
    configured = settings(security_jwt_active_kid="new", security_jwt_keyring=keyring(old=encoded_key(b"o" * 64), new=encoded_key(b"n" * 64)))
    token = sign_access_token("user-id", configured)
    assert jwt.get_unverified_header(token)["kid"] == "new"
    assert validate_access_token(token, configured)["sub"] == "user-id"
    old_payload = {"sub": "user-id", "iss": configured.security_jwt_issuer, "aud": configured.security_jwt_audience, "token_use": "access", "iat": datetime.now(timezone.utc), "exp": datetime(2100, 1, 1, tzinfo=timezone.utc)}
    old_token = jwt.encode(old_payload, configured.jwt_keyring["old"], algorithm="HS256", headers={"kid": "old"})
    assert validate_access_token(old_token, configured)["sub"] == "user-id"
    retired = settings(security_jwt_active_kid="new", security_jwt_keyring=keyring(new=encoded_key(b"n" * 64)))
    with pytest.raises(TokenValidationError):
        validate_access_token(old_token, retired)
    with pytest.raises(TokenValidationError):
        validate_access_token(token + "tampered", configured)
    expired = sign_access_token("user-id", configured, now=datetime(2000, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(TokenValidationError):
        validate_access_token(expired, configured)
    wrong_issuer = sign_access_token("user-id", settings(security_jwt_issuer="other"))
    with pytest.raises(TokenValidationError):
        validate_access_token(wrong_issuer, configured)
    wrong_audience = sign_access_token("user-id", settings(security_jwt_audience="other"))
    with pytest.raises(TokenValidationError):
        validate_access_token(wrong_audience, configured)
    payload = {"sub": "user-id", "iss": configured.security_jwt_issuer, "aud": configured.security_jwt_audience, "iat": datetime.now(timezone.utc), "exp": datetime(2100, 1, 1, tzinfo=timezone.utc)}
    unsupported = jwt.encode(payload, configured.jwt_keyring["new"], algorithm="HS384", headers={"kid": "new"})
    with pytest.raises(TokenValidationError):
        validate_access_token(unsupported, configured)
    unknown = jwt.encode({**payload, "token_use": "access"}, configured.jwt_keyring["new"], algorithm="HS256", headers={"kid": "unknown"})
    with pytest.raises(TokenValidationError):
        validate_access_token(unknown, configured)
    empty_kid = jwt.encode({**payload, "token_use": "access"}, configured.jwt_keyring["new"], algorithm="HS256", headers={"kid": ""})
    with pytest.raises(TokenValidationError):
        validate_access_token(empty_kid, configured)
    refresh = jwt.encode({**payload, "token_use": "refresh"}, configured.jwt_keyring["new"], algorithm="HS256", headers={"kid": "new"})
    with pytest.raises(TokenValidationError):
        validate_access_token(refresh, configured)


def test_environment_and_production_security_requirements() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://user:password@localhost:5432/test", _env_file=None)
    assert settings().app_env == "development"
    with pytest.raises(ValidationError):
        settings(app_env="production", security_jwt_active_kid=None, security_jwt_keyring=None, security_cookie_secure=True, security_hsts_enabled=True)
    with pytest.raises(ValidationError):
        settings(app_env="production", security_cookie_secure=False, security_hsts_enabled=True)
    with pytest.raises(ValidationError):
        settings(app_env="production", security_docs_enabled=True, security_cookie_secure=True, security_hsts_enabled=True)
    with pytest.raises(ValidationError):
        settings(app_env="production", security_cors_allowed_origins="*", security_cookie_secure=True, security_hsts_enabled=True)
    with pytest.raises(ValidationError):
        settings(security_jwt_keyring=keyring(current="abcdefgh" * 4))


def test_keyring_requires_canonical_base64url_keys_and_unambiguous_json() -> None:
    valid = encoded_key()
    configured = settings(security_jwt_active_kid="next", security_jwt_keyring=keyring(current=valid, next=encoded_key()))
    assert set(configured.jwt_keyring) == {"current", "next"}
    assert all(len(key) >= 32 for key in configured.jwt_keyring.values())
    for invalid in (encoded_key(b"x" * 31), "not+base64", valid + "=", "abcdefgh" * 4):
        with pytest.raises(ValidationError):
            settings(security_jwt_keyring=keyring(current=invalid))
    noncanonical = encoded_key(b"\0" * 32)[:-1] + "B"
    with pytest.raises(ValidationError):
        settings(security_jwt_keyring=keyring(current=noncanonical))
    duplicate = '{"current":"%s","current":"%s"}' % (valid, encoded_key())
    with pytest.raises(ValidationError) as error:
        settings(security_jwt_keyring=duplicate)
    assert valid not in str(error.value)
    nested_duplicate = '{"current":"%s","nested":{"kid":1,"kid":2}}' % valid
    with pytest.raises(ValidationError):
        settings(security_jwt_keyring=nested_duplicate)
    with pytest.raises(ValidationError):
        settings(security_jwt_active_kid="missing", security_jwt_keyring=keyring(current=valid))


def test_cors_allowlist_headers_and_documentation_policy() -> None:
    development = create_app(settings(security_docs_enabled=True))
    with TestClient(development) as client:
        allowed = client.get("/health", headers={"Origin": "http://localhost:8501"})
        blocked = client.get("/health", headers={"Origin": "https://untrusted.example"})
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:8501"
        assert "access-control-allow-origin" not in blocked.headers
        assert allowed.headers["x-content-type-options"] == "nosniff"
        preflight = client.options("/health", headers={"Origin": "http://localhost:8501", "Access-Control-Request-Method": "GET"})
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:8501"
        assert preflight.headers["x-content-type-options"] == "nosniff"
        docs = client.get("/docs")
        redoc = client.get("/redoc")
        assert docs.status_code == 200
        assert redoc.status_code == 200
        assert "cdn.jsdelivr.net" in docs.text
        assert "https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]
        assert "cdn.jsdelivr.net" in redoc.text
    production = create_app(settings(app_env="production", security_cookie_secure=True, security_docs_enabled=False, security_hsts_enabled=True))
    with TestClient(production) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health").headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
