from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings

MAX_PASSWORD_BYTES = 1024
_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
_algorithm = "HS256"


class TokenValidationError(Exception):
    pass


def hash_password(password: str) -> str:
    _validate_password_input(password)
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _validate_password_input(password)
    except ValueError:
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def sign_access_token(subject: str, settings: Settings, now: datetime | None = None) -> str:
    if not isinstance(subject, str) or not subject:
        raise TokenValidationError("Token subject is invalid.")
    if not settings.security_jwt_active_kid:
        raise TokenValidationError("Token signing is not configured.")
    issued_at = now or datetime.now(timezone.utc)
    payload = {"sub": subject, "iss": settings.security_jwt_issuer, "aud": settings.security_jwt_audience, "token_use": "access", "iat": issued_at, "exp": issued_at + timedelta(minutes=settings.security_access_token_minutes)}
    return jwt.encode(payload, settings.jwt_keyring[settings.security_jwt_active_kid], algorithm=_algorithm, headers={"kid": settings.security_jwt_active_kid})


def validate_access_token(token: str, settings: Settings) -> dict[str, object]:
    if not settings.security_jwt_keyring:
        raise TokenValidationError("Token validation is not configured.")
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if header.get("alg") != _algorithm or not isinstance(kid, str) or kid not in settings.jwt_keyring:
            raise TokenValidationError("Token header is not accepted.")
        payload = jwt.decode(token, settings.jwt_keyring[kid], algorithms=[_algorithm], issuer=settings.security_jwt_issuer, audience=settings.security_jwt_audience, options={"require": ["sub", "iss", "aud", "token_use", "iat", "exp"]})
        if payload["token_use"] != "access":
            raise TokenValidationError("Token use is not accepted.")
        return payload
    except jwt.PyJWTError as error:
        raise TokenValidationError("Token is invalid.") from error


def _validate_password_input(password: str) -> None:
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password exceeds the maximum supported size.")
