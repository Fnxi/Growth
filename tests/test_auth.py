import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import socket
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_auth
from app.api.auth import get_login_limiter, get_refresh_limiter
from app.auth.limits import AuthRateLimiter
from app.auth.services import AuthAuditService, AuthService, AuthenticationError, RefreshReuseError, SessionService
from app.config import Settings, get_settings
from app.db.models import AuthAuditEvent, AuthSession, RefreshToken, User, UserStatus
from app.db.session import get_session_factory
from app.main import create_app
from app.security.crypto import hash_password

def postgres_available() -> bool:
    try:
        with socket.create_connection(("localhost", 5433), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not postgres_available(), reason="Authentication tests require a reachable PostgreSQL instance.")


def settings() -> Settings:
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("=")
    return Settings(database_url="postgresql+psycopg://user:password@localhost:5432/test", app_env="development", security_jwt_active_kid="test", security_jwt_keyring=json.dumps({"test": key}), security_cors_allowed_origins="http://localhost:8501")


@pytest.fixture
def db() -> Session:
    with get_session_factory()() as session:
        session.execute(delete(AuthAuditEvent))
        session.execute(delete(RefreshToken))
        session.execute(delete(AuthSession))
        session.execute(delete(User))
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(AuthAuditEvent))
        session.execute(delete(RefreshToken))
        session.execute(delete(AuthSession))
        session.execute(delete(User))
        session.commit()


def create_user(session: Session, email: str = "owner@example.com", status: UserStatus = UserStatus.ACTIVE, deleted: bool = False) -> User:
    user = User(email_display=email, email_normalized="ignored", password_hash=hash_password("correct-password"), status=status, deleted_at=datetime.now(timezone.utc) if deleted else None)
    session.add(user)
    session.commit()
    return user


def client(configured: Settings) -> TestClient:
    get_login_limiter.cache_clear()
    get_refresh_limiter.cache_clear()
    app = create_app(configured)
    app.dependency_overrides[get_settings] = lambda: configured
    return TestClient(app)


def test_login_me_refresh_logout_and_audit(db: Session) -> None:
    create_user(db, "Owner@Example.COM")
    configured = settings()
    with client(configured) as http:
        login = http.post("/auth/login", json={"email": " Owner@Example.COM ", "password": "correct-password"})
        assert login.status_code == 200
        tokens = login.json()
        me = http.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert me.status_code == 200
        assert me.json()["email"] == "Owner@Example.COM"
        refreshed = http.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refreshed.status_code == 200
        reuse = http.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert reuse.status_code == 401
        assert http.get("/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"}).status_code == 401
    events = {event.event_type for event in db.scalars(select(AuthAuditEvent))}
    assert {"login_success", "refresh_success", "refresh_reuse_detected", "session_revoked"} <= events
    assert all("token" not in event.metadata_json and "password" not in event.metadata_json for event in db.scalars(select(AuthAuditEvent)))


@pytest.mark.parametrize("email,password,status,deleted", [("owner@example.com", "wrong", UserStatus.ACTIVE, False), ("missing@example.com", "correct-password", UserStatus.ACTIVE, False), ("disabled@example.com", "correct-password", UserStatus.DISABLED, False), ("deleted@example.com", "correct-password", UserStatus.ACTIVE, True)])
def test_login_failures_are_generic(db: Session, email: str, password: str, status: UserStatus, deleted: bool) -> None:
    if email != "missing@example.com":
        create_user(db, email, status, deleted)
    with client(settings()) as http:
        response = http.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials."}


@pytest.mark.parametrize(("path", "payload", "secret", "detail"), [
    ("/auth/refresh", {"refresh_token": "short-secret"}, "short-secret", "Invalid refresh token."),
    ("/auth/refresh", {"refresh_token": "x" * 513}, "x" * 513, "Invalid refresh token."),
    ("/auth/refresh", {"refresh_token": ["wrong-type-secret"]}, "wrong-type-secret", "Invalid refresh token."),
    ("/auth/login", {"email": "owner@example.com", "password": ""}, "", "Invalid credentials."),
    ("/auth/login", {"email": "owner@example.com", "password": "p" * 1025}, "p" * 1025, "Invalid credentials."),
    ("/auth/login", {"email": "owner@example.com"}, "owner@example.com", "Invalid credentials."),
])
def test_auth_validation_errors_do_not_reflect_credentials(path: str, payload: dict[str, object], secret: str, detail: str) -> None:
    with client(settings()) as http:
        response = http.post(path, json=payload)
    assert response.status_code == 401
    assert response.json() == {"detail": detail}
    assert not secret or secret not in response.text


def test_session_expiry_logout_all_and_rate_limiter(db: Session) -> None:
    user = create_user(db)
    service = AuthService(settings())
    _, first_session, first_access, _ = service.login(db, user.email_display, "correct-password", None, None)
    _, second_session, _, _ = service.login(db, user.email_display, "correct-password", None, None)
    first_session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    with client(settings()) as http:
        assert http.get("/auth/me", headers={"Authorization": f"Bearer {first_access}"}).status_code == 401
        access = service.access_token(user, second_session)
        assert http.post("/auth/logout-all", headers={"Authorization": f"Bearer {access}"}).status_code == 204
        assert http.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401
    limiter = AuthRateLimiter(1, 60)
    assert limiter.allow("ip", "email") is None
    assert limiter.allow("ip", "other-email") is not None


def test_refresh_rotation_is_single_success_under_concurrency(db: Session) -> None:
    user = create_user(db)
    service = AuthService(settings())
    _, _, _, refresh = service.login(db, user.email_display, "correct-password", None, None)
    barrier = Barrier(2)

    def rotate() -> str:
        with get_session_factory()() as worker_session:
            barrier.wait()
            try:
                service.refresh_tokens.rotate(worker_session, refresh, settings(), datetime.now(timezone.utc), service.audit)
                worker_session.commit()
                return "success"
            except RefreshReuseError:
                worker_session.commit()
                return "reuse"
            except AuthenticationError:
                worker_session.rollback()
                return "invalid"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    assert sorted(results) == ["reuse", "success"]
    assert db.scalar(select(AuthSession.revoked_at).where(AuthSession.user_id == user.id)) is not None


def test_refresh_of_old_and_successor_tokens_revokes_family_without_deadlock(db: Session) -> None:
    user = create_user(db)
    service = AuthService(settings())
    _, _, _, old_token = service.login(db, user.email_display, "correct-password", None, None)
    _, auth_session, successor_token = service.refresh_tokens.rotate(db, old_token, settings(), datetime.now(timezone.utc), service.audit)
    db.commit()
    barrier = Barrier(2)

    def rotate(raw_token: str) -> str:
        with get_session_factory()() as worker_session:
            barrier.wait()
            try:
                service.refresh_tokens.rotate(worker_session, raw_token, settings(), datetime.now(timezone.utc), service.audit)
                worker_session.commit()
                return "success"
            except RefreshReuseError:
                worker_session.commit()
                return "reuse"
            except AuthenticationError:
                worker_session.rollback()
                return "invalid"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(rotate, raw_token) for raw_token in (old_token, successor_token)]
        results = [future.result(timeout=15) for future in futures]
    assert "reuse" in results
    db.expire_all()
    assert db.get(AuthSession, auth_session.id).revoked_at is not None
    family = list(db.scalars(select(RefreshToken).where(RefreshToken.session_id == auth_session.id)))
    assert family and all(token.revoked_at is not None for token in family)


def test_refresh_racing_logout_and_logout_all_leaves_session_revoked(db: Session) -> None:
    user = create_user(db)
    service = AuthService(settings())
    _, auth_session, _, refresh_token = service.login(db, user.email_display, "correct-password", None, None)
    barrier = Barrier(2)

    def revoke_all() -> str:
        with get_session_factory()() as worker_session:
            barrier.wait()
            locked_user = service.sessions.lock_user(worker_session, user.id)
            sessions = list(worker_session.scalars(select(AuthSession).where(AuthSession.user_id == locked_user.id, AuthSession.revoked_at.is_(None)).order_by(AuthSession.id).with_for_update()))
            for item in sessions:
                service.sessions.revoke(worker_session, item, datetime.now(timezone.utc), "logout_all", service.audit)
            worker_session.commit()
            return "logout_all"

    def refresh() -> str:
        with get_session_factory()() as worker_session:
            barrier.wait()
            try:
                service.refresh_tokens.rotate(worker_session, refresh_token, settings(), datetime.now(timezone.utc), service.audit)
                worker_session.commit()
                return "success"
            except AuthenticationError:
                worker_session.rollback()
                return "invalid"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(action) for action in (refresh, revoke_all)]
        results = [future.result(timeout=15) for future in futures]
    assert "logout_all" in results
    db.expire_all()
    assert db.get(AuthSession, auth_session.id).revoked_at is not None
    assert all(token.revoked_at is not None for token in db.scalars(select(RefreshToken).where(RefreshToken.session_id == auth_session.id)))


def test_refresh_racing_individual_logout_leaves_session_revoked(db: Session) -> None:
    user = create_user(db)
    service = AuthService(settings())
    _, auth_session, _, refresh_token = service.login(db, user.email_display, "correct-password", None, None)
    barrier = Barrier(2)

    def logout() -> str:
        with get_session_factory()() as worker_session:
            barrier.wait()
            service.sessions.lock_user(worker_session, user.id)
            locked_session = service.sessions.lock_session(worker_session, auth_session.id, user.id)
            service.sessions.revoke(worker_session, locked_session, datetime.now(timezone.utc), "logout", service.audit)
            worker_session.commit()
            return "logout"

    def refresh() -> str:
        with get_session_factory()() as worker_session:
            barrier.wait()
            try:
                service.refresh_tokens.rotate(worker_session, refresh_token, settings(), datetime.now(timezone.utc), service.audit)
                worker_session.commit()
                return "success"
            except AuthenticationError:
                worker_session.rollback()
                return "invalid"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(action) for action in (refresh, logout)]
        results = [future.result(timeout=15) for future in futures]
    assert "logout" in results
    db.expire_all()
    assert db.get(AuthSession, auth_session.id).revoked_at is not None
    assert all(token.revoked_at is not None for token in db.scalars(select(RefreshToken).where(RefreshToken.session_id == auth_session.id)))


def test_login_completed_before_logout_all_is_revoked(db: Session) -> None:
    user = create_user(db)
    service = AuthService(settings())
    _, original_session, _, _ = service.login(db, user.email_display, "correct-password", None, None)

    login_locked_user = Event()
    release_login = Event()

    class CoordinatedSessions(SessionService):
        def create(self, session: Session, user: User, configured: Settings, ip_hash: bytes | None, user_agent: str | None, now: datetime) -> AuthSession:
            created = super().create(session, user, configured, ip_hash, user_agent, now)
            login_locked_user.set()
            assert release_login.wait(timeout=15)
            return created

    login_service = AuthService(settings(), session_service=CoordinatedSessions())
    def login() -> AuthSession:
        with get_session_factory()() as worker_session:
            _, created, _, _ = login_service.login(worker_session, user.email_display, "correct-password", None, None)
            return created

    def logout_all() -> None:
        with get_session_factory()() as worker_session:
            locked_user = service.sessions.lock_user(worker_session, user.id)
            active_sessions = list(worker_session.scalars(select(AuthSession).where(AuthSession.user_id == locked_user.id, AuthSession.revoked_at.is_(None)).order_by(AuthSession.id).with_for_update()))
            for item in active_sessions:
                service.sessions.revoke(worker_session, item, datetime.now(timezone.utc), "logout_all", service.audit)
            worker_session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        login_future = pool.submit(login)
        assert login_locked_user.wait(timeout=15)
        logout_future = pool.submit(logout_all)
        release_login.set()
        new_session = login_future.result(timeout=15)
        logout_future.result(timeout=15)
    db.expire_all()
    assert db.get(AuthSession, original_session.id).revoked_at is not None
    assert db.get(AuthSession, new_session.id).revoked_at is not None


def test_login_after_logout_all_creates_an_active_session(db: Session) -> None:
    user = create_user(db)
    service = AuthService(settings())
    _, active_session, _, _ = service.login(db, user.email_display, "correct-password", None, None)
    locked_user = service.sessions.lock_user(db, user.id)
    for item in db.scalars(select(AuthSession).where(AuthSession.user_id == locked_user.id, AuthSession.revoked_at.is_(None)).order_by(AuthSession.id).with_for_update()):
        service.sessions.revoke(db, item, datetime.now(timezone.utc), "logout_all", service.audit)
    db.commit()
    _, new_session, _, _ = service.login(db, user.email_display, "correct-password", None, None)
    db.expire_all()
    assert db.get(AuthSession, active_session.id).revoked_at is not None
    assert db.get(AuthSession, new_session.id).revoked_at is None


def test_audit_metadata_allowlist_drops_sensitive_values(db: Session) -> None:
    audit = AuthAuditService()
    audit.record(db, "login_failure", metadata={"source": "test", "password": "secret", "refresh_token": "secret", "nested": {"token": "secret"}})
    db.commit()
    assert db.scalar(select(AuthAuditEvent.metadata_json)) == {"source": "test"}
