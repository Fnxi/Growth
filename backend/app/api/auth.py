from functools import lru_cache
from datetime import datetime, timezone
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_auth
from app.auth.limits import AuthRateLimiter
from app.auth.services import AuthService, AuthenticationError, RefreshReuseError
from app.config import Settings, get_settings
from app.db.models import AuthSession, MembershipStatus, UserStatus
from app.db.session import get_db
from app.schemas import AuthLoginRequest, AuthMeRead, AuthRefreshRequest, AuthTokenRead, MembershipRead

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(settings: Settings = Depends(get_settings)) -> AuthService:
    return AuthService(settings)


@lru_cache
def get_login_limiter() -> AuthRateLimiter:
    settings = get_settings()
    return AuthRateLimiter(settings.security_auth_rate_limit, settings.security_auth_rate_window_seconds)


@lru_cache
def get_refresh_limiter() -> AuthRateLimiter:
    settings = get_settings()
    return AuthRateLimiter(settings.security_refresh_rate_limit, settings.security_refresh_rate_window_seconds)


def client_ip_hash(request: Request) -> bytes:
    return sha256((request.client.host if request.client else "unknown").encode("utf-8")).digest()


def rate_limit_or_429(limiter: AuthRateLimiter, *keys: str) -> None:
    retry_after = limiter.allow(*keys)
    if retry_after:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many authentication attempts.", headers={"Retry-After": str(retry_after)})


def token_response(access_token: str, refresh_token: str, settings: Settings) -> AuthTokenRead:
    return AuthTokenRead(access_token=access_token, refresh_token=refresh_token, expires_in=settings.security_access_token_minutes * 60)


@router.post("/login", response_model=AuthTokenRead)
def login(payload: AuthLoginRequest, request: Request, session: Session = Depends(get_db), service: AuthService = Depends(get_auth_service)) -> AuthTokenRead:
    ip_hash = client_ip_hash(request)
    rate_limit_or_429(get_login_limiter(), f"login:ip:{ip_hash.hex()}", f"login:email:{sha256(payload.email.strip().casefold().encode('utf-8')).hexdigest()}")
    try:
        _, _, access_token, refresh_token = service.login(session, payload.email, payload.password, ip_hash, request.headers.get("user-agent"))
    except AuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.") from error
    return token_response(access_token, refresh_token, service.settings)


@router.post("/refresh", response_model=AuthTokenRead)
def refresh(payload: AuthRefreshRequest, request: Request, session: Session = Depends(get_db), service: AuthService = Depends(get_auth_service)) -> AuthTokenRead:
    rate_limit_or_429(get_refresh_limiter(), f"refresh:ip:{client_ip_hash(request).hex()}", f"refresh:token:{sha256(payload.refresh_token.encode('utf-8')).hexdigest()}")
    try:
        user, auth_session, refresh_token = service.refresh_tokens.rotate(session, payload.refresh_token, service.settings, datetime.now(timezone.utc), service.audit)
        access_token = service.access_token(user, auth_session)
        session.commit()
    except RefreshReuseError as error:
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.") from error
    except AuthenticationError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.") from error
    return token_response(access_token, refresh_token, service.settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current: tuple = Depends(get_current_auth), session: Session = Depends(get_db), service: AuthService = Depends(get_auth_service)) -> Response:
    user, auth_session = current
    locked_user = service.sessions.lock_user(session, user.id)
    locked_session = service.sessions.lock_session(session, auth_session.id, user.id)
    if locked_user is None or locked_user.status != UserStatus.ACTIVE or locked_user.deleted_at is not None or locked_session is None or locked_session.revoked_at is not None:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.", headers={"WWW-Authenticate": "Bearer"})
    service.sessions.revoke(session, locked_session, datetime.now(timezone.utc), "logout", service.audit, event_type="logout")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(current: tuple = Depends(get_current_auth), session: Session = Depends(get_db), service: AuthService = Depends(get_auth_service)) -> Response:
    user, _ = current
    locked_user = service.sessions.lock_user(session, user.id)
    if locked_user is None or locked_user.status != UserStatus.ACTIVE or locked_user.deleted_at is not None:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.", headers={"WWW-Authenticate": "Bearer"})
    now = datetime.now(timezone.utc)
    active_sessions = list(session.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).order_by(AuthSession.id).with_for_update()))
    for auth_session in active_sessions:
        service.sessions.revoke(session, auth_session, now, "logout_all", service.audit, event_type="session_revoked")
    service.audit.record(session, "logout_all", user_id=user.id, metadata={"session_count": len(active_sessions)})
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=AuthMeRead)
def me(current: tuple = Depends(get_current_auth)) -> AuthMeRead:
    user, _ = current
    memberships = [MembershipRead(organization_id=item.organization_id, role=item.role, status=item.status) for item in user.memberships if item.status == MembershipStatus.ACTIVE]
    return AuthMeRead(id=user.id, email=user.email_display, status=user.status, platform_role=user.platform_role, memberships=memberships)
