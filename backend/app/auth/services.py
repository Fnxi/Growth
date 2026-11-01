from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.db.models import AuthAuditEvent, AuthSession, MembershipStatus, RefreshToken, User, UserStatus, normalize_email
from app.security.crypto import hash_password, sign_access_token, verify_password

_dummy_password_hash = hash_password("not-a-real-password-for-timing-equalization")
_metadata_keys = {"auth_method", "session_count", "reason", "source"}


class AuthenticationError(Exception):
    pass


class RefreshReuseError(AuthenticationError):
    pass


class AuthAuditService:
    def record(self, session: Session, event_type: str, *, user_id: UUID | None = None, session_id: UUID | None = None, organization_id: UUID | None = None, ip_hash: bytes | None = None, user_agent: str | None = None, reason_code: str | None = None, metadata: dict[str, object] | None = None) -> None:
        safe_metadata = {key: value for key, value in (metadata or {}).items() if key in _metadata_keys and isinstance(value, (str, int, bool)) and len(str(value)) <= 100}
        session.add(AuthAuditEvent(user_id=user_id, session_id=session_id, organization_id=organization_id, event_type=event_type, ip_hash=ip_hash, user_agent=(user_agent or "")[:512] or None, reason_code=reason_code, metadata_json=safe_metadata))


class SessionService:
    def lock_user(self, session: Session, user_id: UUID) -> User | None:
        return session.scalar(select(User).where(User.id == user_id).with_for_update())

    def lock_session(self, session: Session, session_id: UUID, user_id: UUID) -> AuthSession | None:
        return session.scalar(select(AuthSession).options(selectinload(AuthSession.user)).where(AuthSession.id == session_id, AuthSession.user_id == user_id).with_for_update())

    def create(self, session: Session, user: User, settings: Settings, ip_hash: bytes | None, user_agent: str | None, now: datetime) -> AuthSession:
        auth_session = AuthSession(user_id=user.id, expires_at=now + timedelta(days=settings.security_session_max_days), ip_hash=ip_hash, user_agent=(user_agent or "")[:512] or None)
        session.add(auth_session)
        session.flush()
        return auth_session

    def revoke(self, session: Session, auth_session: AuthSession, now: datetime, reason: str, audit: AuthAuditService, *, event_type: str = "session_revoked") -> None:
        if auth_session.revoked_at is None:
            auth_session.revoked_at = now
            auth_session.revoked_reason = reason
            for token in session.scalars(select(RefreshToken).where(RefreshToken.session_id == auth_session.id, RefreshToken.revoked_at.is_(None)).order_by(RefreshToken.id).with_for_update()):
                token.revoked_at = now
            audit.record(session, event_type, user_id=auth_session.user_id, session_id=auth_session.id, reason_code=reason)


class RefreshTokenService:
    def issue(self, session: Session, auth_session: AuthSession, settings: Settings, now: datetime, family_id: UUID | None = None, parent: RefreshToken | None = None) -> tuple[RefreshToken, str]:
        raw_token = token_urlsafe(48)
        expires_at = min(now + timedelta(days=settings.security_refresh_token_days), auth_session.expires_at)
        token = RefreshToken(session_id=auth_session.id, family_id=family_id or uuid4(), parent_token_id=parent.id if parent else None, token_hash=sha256(raw_token.encode("utf-8")).digest(), expires_at=expires_at)
        session.add(token)
        session.flush()
        if parent:
            parent.used_at = now
            parent.replaced_by_token_id = token.id
        return token, raw_token

    def rotate(self, session: Session, raw_token: str, settings: Settings, now: datetime, audit: AuthAuditService) -> tuple[User, AuthSession, str]:
        token_hash = sha256(raw_token.encode("utf-8")).digest()
        resolved = session.execute(select(RefreshToken.session_id, RefreshToken.family_id, AuthSession.user_id).join(AuthSession, AuthSession.id == RefreshToken.session_id).where(RefreshToken.token_hash == token_hash)).one_or_none()
        if resolved is None:
            raise AuthenticationError("Invalid refresh token.")
        session_id, family_id, user_id = resolved
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        auth_session = session.scalar(select(AuthSession).options(selectinload(AuthSession.user)).where(AuthSession.id == session_id, AuthSession.user_id == user_id).with_for_update())
        family = list(session.scalars(select(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.session_id == session_id).order_by(RefreshToken.id).with_for_update()))
        token = next((item for item in family if item.token_hash == token_hash), None)
        if user is None or auth_session is None or token is None:
            raise AuthenticationError("Invalid refresh token.")
        expired = token.expires_at <= now or auth_session.expires_at <= now
        inactive = auth_session.revoked_at is not None or user.status != UserStatus.ACTIVE or user.deleted_at is not None
        if token.used_at is not None:
            for item in family:
                if item.revoked_at is None:
                    item.revoked_at = now
            auth_session.revoked_at = now
            auth_session.revoked_reason = "refresh_reuse"
            audit.record(session, "refresh_reuse_detected", user_id=user.id, session_id=auth_session.id, reason_code="token_reused")
            audit.record(session, "session_revoked", user_id=user.id, session_id=auth_session.id, reason_code="refresh_reuse")
            raise RefreshReuseError("Invalid refresh token.")
        if token.revoked_at is not None or expired or inactive:
            raise AuthenticationError("Invalid refresh token.")
        _, successor = self.issue(session, auth_session, settings, now, family_id=token.family_id, parent=token)
        auth_session.last_seen_at = now
        audit.record(session, "refresh_success", user_id=user.id, session_id=auth_session.id, metadata={"auth_method": auth_session.auth_method})
        return user, auth_session, successor


class AuthService:
    def __init__(self, settings: Settings, session_service: SessionService | None = None, refresh_service: RefreshTokenService | None = None, audit_service: AuthAuditService | None = None) -> None:
        self.settings = settings
        self.sessions = session_service or SessionService()
        self.refresh_tokens = refresh_service or RefreshTokenService()
        self.audit = audit_service or AuthAuditService()

    def login(self, session: Session, email: str, password: str, ip_hash: bytes | None, user_agent: str | None, now: datetime | None = None) -> tuple[User, AuthSession, str, str]:
        now = now or datetime.now(timezone.utc)
        try:
            normalized = normalize_email(email)
        except ValueError:
            verify_password(password, _dummy_password_hash)
            self.audit.record(session, "login_failure", ip_hash=ip_hash, user_agent=user_agent, reason_code="invalid_credentials")
            session.commit()
            raise AuthenticationError("Invalid credentials.")
        candidate = session.scalar(select(User).where(User.email_normalized == normalized))
        valid_password = verify_password(password, candidate.password_hash if candidate else _dummy_password_hash)
        user = session.scalar(select(User).where(User.id == candidate.id).with_for_update()) if candidate else None
        if user is None or not valid_password or user.status != UserStatus.ACTIVE or user.deleted_at is not None:
            self.audit.record(session, "login_failure", user_id=user.id if user else None, ip_hash=ip_hash, user_agent=user_agent, reason_code="invalid_credentials")
            session.commit()
            raise AuthenticationError("Invalid credentials.")
        auth_session = self.sessions.create(session, user, self.settings, ip_hash, user_agent, now)
        _, refresh_token = self.refresh_tokens.issue(session, auth_session, self.settings, now)
        user.last_login_at = now
        self.audit.record(session, "login_success", user_id=user.id, session_id=auth_session.id, ip_hash=ip_hash, user_agent=user_agent, metadata={"auth_method": auth_session.auth_method})
        access_token = sign_access_token(str(user.id), self.settings, auth_session.id, now=now)
        session.commit()
        return user, auth_session, access_token, refresh_token

    def access_token(self, user: User, auth_session: AuthSession, now: datetime | None = None) -> str:
        return sign_access_token(str(user.id), self.settings, auth_session.id, now=now)
