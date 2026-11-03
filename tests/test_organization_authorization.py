import base64
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.config import Settings, get_settings
from app.db.models import AuthSession, MembershipStatus, Organization, OrganizationMembership, OrganizationRole, OrganizationStatus, User, UserStatus
from app.db.session import get_db
from app.security.crypto import sign_access_token


class FakeSession:
    def __init__(self, user: User, auth_session: AuthSession, membership: OrganizationMembership | None):
        self.user = user
        self.auth_session = auth_session
        self.membership = membership
        self.commits = 0
        self.last_scalar_statement = None

    def get(self, model, identifier):
        if model is User and identifier == self.user.id:
            return self.user
        if model is AuthSession and identifier == self.auth_session.id:
            return self.auth_session
        return None

    def scalar(self, statement):
        self.last_scalar_statement = statement
        membership = self.membership
        if membership is None or membership.status is not MembershipStatus.ACTIVE:
            return None
        if membership.organization.status is not OrganizationStatus.ACTIVE or membership.organization.deleted_at is not None:
            return None
        return membership

    def commit(self):
        self.commits += 1


def settings() -> Settings:
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("=")
    return Settings(
        database_url="postgresql+psycopg://user:password@localhost:5432/test",
        app_env="development",
        security_jwt_active_kid="test",
        security_jwt_keyring=json.dumps({"test": key}),
        security_cors_allowed_origins="http://localhost:8501",
    )


def principal(role: OrganizationRole = OrganizationRole.OWNER) -> tuple[FakeSession, Organization]:
    organization = Organization(name="Acme", slug_normalized="acme", status=OrganizationStatus.ACTIVE)
    organization.id = uuid4()
    user = User(email_display="owner@example.com", email_normalized="owner@example.com", password_hash="unused", status=UserStatus.ACTIVE)
    user.id = uuid4()
    auth_session = AuthSession(user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    auth_session.id = uuid4()
    membership = OrganizationMembership(
        user_id=user.id,
        organization_id=organization.id,
        role=role,
        status=MembershipStatus.ACTIVE,
    )
    membership.id = uuid4()
    membership.organization = organization
    return FakeSession(user, auth_session, membership), organization


def client(session: FakeSession, configured: Settings) -> TestClient:
    app = FastAPI()

    @app.get("/organizations/{organization_id}/read")
    def read(context: OrgContext = Depends(require_org_roles(*CommercialRole))):
        return {"organization_id": str(context.organization.id), "role": context.role}

    @app.post("/organizations/{organization_id}/write")
    def write(context: OrgContext = Depends(require_org_roles(CommercialRole.OWNER, CommercialRole.ADMIN, CommercialRole.EDITOR))):
        return {"role": context.role}

    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def bearer(session: FakeSession, configured: Settings) -> dict[str, str]:
    token = sign_access_token(str(session.user.id), configured, session.auth_session.id)
    return {"Authorization": f"Bearer {token}"}


def test_org_context_accepts_active_membership_and_legacy_analyst_as_editor() -> None:
    session, organization = principal(OrganizationRole.ANALYST)
    configured = settings()
    with client(session, configured) as http:
        response = http.post(f"/organizations/{organization.id}/write", headers=bearer(session, configured))
    assert response.status_code == 200
    assert response.json()["role"] == CommercialRole.EDITOR
    query = str(session.last_scalar_statement)
    assert "organization_memberships.user_id" in query
    assert "organization_memberships.organization_id" in query
    assert "organization_memberships.status" in query
    assert "organizations.status" in query
    assert "organizations.deleted_at" in query


@pytest.mark.parametrize("role,write_status", [
    (OrganizationRole.OWNER, 200),
    (OrganizationRole.ADMIN, 200),
    (OrganizationRole.ANALYST, 200),
    (OrganizationRole.VIEWER, 403),
])
def test_org_role_permissions(role: OrganizationRole, write_status: int) -> None:
    session, organization = principal(role)
    configured = settings()
    with client(session, configured) as http:
        assert http.get(f"/organizations/{organization.id}/read", headers=bearer(session, configured)).status_code == 200
        assert http.post(f"/organizations/{organization.id}/write", headers=bearer(session, configured)).status_code == write_status


@pytest.mark.parametrize("state", ["missing", "suspended", "inactive_organization"])
def test_org_context_rejects_missing_or_inactive_membership(state: str) -> None:
    session, organization = principal()
    if state == "missing":
        session.membership = None
    elif state == "suspended":
        session.membership.status = MembershipStatus.SUSPENDED
    else:
        session.membership.organization.status = OrganizationStatus.SUSPENDED
    configured = settings()
    with client(session, configured) as http:
        response = http.get(f"/organizations/{organization.id}/read", headers=bearer(session, configured))
    assert response.status_code == 403


def test_org_context_rejects_missing_auth_disabled_user_and_revoked_session() -> None:
    session, organization = principal()
    configured = settings()
    with client(session, configured) as http:
        assert http.get(f"/organizations/{organization.id}/read").status_code == 401
        session.user.status = UserStatus.DISABLED
        assert http.get(f"/organizations/{organization.id}/read", headers=bearer(session, configured)).status_code == 401
        session.user.status = UserStatus.ACTIVE
        session.auth_session.revoked_at = datetime.now(timezone.utc)
        assert http.get(f"/organizations/{organization.id}/read", headers=bearer(session, configured)).status_code == 401


def test_role_and_membership_changes_apply_to_existing_access_token() -> None:
    session, organization = principal(OrganizationRole.VIEWER)
    configured = settings()
    headers = bearer(session, configured)
    with client(session, configured) as http:
        assert http.post(f"/organizations/{organization.id}/write", headers=headers).status_code == 403
        session.membership.role = OrganizationRole.ADMIN
        assert http.post(f"/organizations/{organization.id}/write", headers=headers).status_code == 200
        session.membership.status = MembershipStatus.SUSPENDED
        assert http.get(f"/organizations/{organization.id}/read", headers=headers).status_code == 403


def test_org_context_rejects_another_organization_path() -> None:
    session, _ = principal()
    configured = settings()
    with client(session, configured) as http:
        response = http.get(f"/organizations/{uuid4()}/read", headers=bearer(session, configured))
    assert response.status_code == 403
