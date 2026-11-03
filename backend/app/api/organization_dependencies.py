from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from app.api.auth_dependencies import get_current_auth
from app.db.models import (
    AuthSession,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrganizationStatus,
    User,
)
from app.db.session import get_db


class CommercialRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    READER = "reader"


@dataclass(frozen=True)
class OrgContext:
    """Authenticated principal and active organization resolved for one request."""

    user: User
    auth_session: AuthSession
    organization: Organization
    membership: OrganizationMembership
    role: CommercialRole


def commercial_role(role: OrganizationRole) -> CommercialRole:
    """Map persisted legacy role names to the commercial permission vocabulary."""

    return {
        OrganizationRole.OWNER: CommercialRole.OWNER,
        OrganizationRole.ADMIN: CommercialRole.ADMIN,
        OrganizationRole.ANALYST: CommercialRole.EDITOR,
        OrganizationRole.VIEWER: CommercialRole.READER,
    }[role]


def get_org_context(
    organization_id: UUID = Path(),
    current: tuple[User, AuthSession] = Depends(get_current_auth),
    session: Session = Depends(get_db),
) -> OrgContext:
    user, auth_session = current
    membership = session.scalar(
        select(OrganizationMembership)
        .join(OrganizationMembership.organization)
        .options(contains_eager(OrganizationMembership.organization))
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
            Organization.status == OrganizationStatus.ACTIVE,
            Organization.deleted_at.is_(None),
        )
    )
    if membership is None or membership.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active organization membership is required.",
        )
    return OrgContext(
        user=user,
        auth_session=auth_session,
        organization=membership.organization,
        membership=membership,
        role=commercial_role(membership.role),
    )


def require_org_roles(*allowed_roles: CommercialRole):
    if not allowed_roles:
        raise ValueError("At least one organization role is required.")
    allowed = frozenset(allowed_roles)

    def dependency(context: OrgContext = Depends(get_org_context)) -> OrgContext:
        if context.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization permission is required.",
            )
        return context

    return dependency
