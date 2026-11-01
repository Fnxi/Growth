"""add identity schema

Revision ID: d8f7a1c4e902
Revises: ba9d803f6c72
Create Date: 2026-10-31 22:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d8f7a1c4e902"
down_revision: Union[str, Sequence[str], None] = "ba9d803f6c72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_status = postgresql.ENUM("active", "disabled", name="user_status", create_type=False)
    platform_role = postgresql.ENUM("standard", "platform_admin", name="platform_role", create_type=False)
    organization_status = postgresql.ENUM("active", "suspended", "archived", name="organization_status", create_type=False)
    organization_role = postgresql.ENUM("owner", "admin", "analyst", "viewer", name="organization_role", create_type=False)
    membership_status = postgresql.ENUM("active", "suspended", "removed", name="membership_status", create_type=False)
    bind = op.get_bind()
    for enum_type in (user_status, platform_role, organization_status, organization_role, membership_status):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("email_display", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", user_status, server_default="active", nullable=False),
        sa.Column("platform_role", platform_role, server_default="standard", nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_normalized", name="uq_user_email_normalized"),
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug_normalized", sa.String(length=100), nullable=False),
        sa.Column("status", organization_status, server_default="active", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug_normalized", name="uq_organization_slug_normalized"),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("role", organization_role, nullable=False),
        sa.Column("status", membership_status, server_default="active", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_membership_user_organization"),
    )
    op.create_index("ix_membership_user_status", "organization_memberships", ["user_id", "status"])
    op.create_index("ix_membership_organization_status", "organization_memberships", ["organization_id", "status"])
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=100), nullable=True),
        sa.Column("ip_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("auth_method", sa.String(length=50), server_default="password", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_session_user_active", "auth_sessions", ["user_id", "revoked_at", "expires_at"])
    op.create_table(
        "refresh_tokens",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("parent_token_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["parent_token_id"], ["refresh_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["replaced_by_token_id"], ["refresh_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
    )
    op.create_index("ix_refresh_token_session", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_token_family", "refresh_tokens", ["family_id"])
    op.create_table(
        "auth_audit_events",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_audit_event_user_occurred", "auth_audit_events", ["user_id", "occurred_at"])
    op.create_index("ix_auth_audit_event_organization_occurred", "auth_audit_events", ["organization_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_audit_event_organization_occurred", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_event_user_occurred", table_name="auth_audit_events")
    op.drop_table("auth_audit_events")
    op.drop_index("ix_refresh_token_family", table_name="refresh_tokens")
    op.drop_index("ix_refresh_token_session", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_auth_session_user_active", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_membership_organization_status", table_name="organization_memberships")
    op.drop_index("ix_membership_user_status", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.drop_table("users")
    bind = op.get_bind()
    for enum_name in ("membership_status", "organization_role", "organization_status", "platform_role", "user_status"):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
