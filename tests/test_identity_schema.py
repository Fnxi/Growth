from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuthAuditEvent, AuthSession, Organization, OrganizationMembership, OrganizationRole, RefreshToken, User
from app.db.session import get_session_factory

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") and not Path(".env").exists(),
    reason="Identity schema tests require DATABASE_URL or a local .env file.",
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    with get_session_factory()() as db_session:
        db_session.execute(delete(AuthAuditEvent))
        db_session.execute(delete(RefreshToken))
        db_session.execute(delete(AuthSession))
        db_session.execute(delete(OrganizationMembership))
        db_session.execute(delete(Organization))
        db_session.execute(delete(User))
        db_session.commit()
        yield db_session
        db_session.rollback()
        db_session.execute(delete(AuthAuditEvent))
        db_session.execute(delete(RefreshToken))
        db_session.execute(delete(AuthSession))
        db_session.execute(delete(OrganizationMembership))
        db_session.execute(delete(Organization))
        db_session.execute(delete(User))
        db_session.commit()


def create_user(session: Session, email: str = "Owner@Example.COM") -> User:
    user = User(email_display=email, email_normalized="ignored", password_hash="$argon2id$example")
    session.add(user)
    session.commit()
    return user


def test_user_email_normalization_and_organization_membership_uniqueness(session: Session) -> None:
    user = create_user(session, " Owner@Example.COM ")
    organization = Organization(name="Example Inc.", slug_normalized="Example-Inc")
    session.add(organization)
    session.commit()
    assert user.email_display == "Owner@Example.COM"
    assert user.email_normalized == "owner@example.com"
    assert organization.slug_normalized == "example-inc"
    membership = OrganizationMembership(user_id=user.id, organization_id=organization.id, role=OrganizationRole.OWNER)
    session.add(membership)
    session.commit()
    assert membership.user == user
    assert membership.organization == organization
    session.add(User(email_display="owner@example.com", email_normalized="ignored", password_hash="$argon2id$example"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(OrganizationMembership(user_id=user.id, organization_id=organization.id, role=OrganizationRole.VIEWER))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_sessions_refresh_token_lineage_audit_and_delete_constraints(session: Session) -> None:
    user = create_user(session)
    organization = Organization(name="Example Inc.", slug_normalized="example-inc")
    session.add(organization)
    session.commit()
    auth_session = AuthSession(user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(days=30), ip_hash=b"i" * 32, user_agent="pytest")
    session.add(auth_session)
    session.commit()
    first = RefreshToken(session_id=auth_session.id, family_id=uuid4(), token_hash=b"a" * 32, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    session.add(first)
    session.commit()
    successor = RefreshToken(session_id=auth_session.id, family_id=first.family_id, parent_token_id=first.id, token_hash=b"b" * 32, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    session.add(successor)
    session.flush()
    first.replaced_by_token_id = successor.id
    session.commit()
    assert session.scalar(select(RefreshToken).where(RefreshToken.id == successor.id)).parent_token_id == first.id
    assert session.scalar(select(RefreshToken).where(RefreshToken.id == first.id)).replaced_by_token_id == successor.id
    session.add(RefreshToken(session_id=auth_session.id, family_id=first.family_id, token_hash=b"b" * 32, expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    audit = AuthAuditEvent(user_id=user.id, session_id=auth_session.id, organization_id=organization.id, event_type="login_succeeded", metadata_json={"source": "test"})
    session.add(audit)
    session.commit()
    assert "password" not in AuthAuditEvent.__table__.columns
    assert "token_hash" not in AuthAuditEvent.__table__.columns
    with pytest.raises(IntegrityError):
        session.execute(delete(User).where(User.id == user.id))
        session.commit()
    session.rollback()
    session.execute(delete(AuthSession).where(AuthSession.id == auth_session.id))
    session.commit()
    assert session.scalar(select(RefreshToken).where(RefreshToken.session_id == auth_session.id)) is None
    assert session.scalar(select(AuthAuditEvent.session_id).where(AuthAuditEvent.id == audit.id)) is None
