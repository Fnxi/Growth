from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import re
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    LargeBinary,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
    UniqueConstraint,
    func,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampedModel, UUIDModel


class MetricClassification(StrEnum):
    OBSERVED = "observed"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InfrastructureSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SchedulerRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PlatformRole(StrEnum):
    STANDARD = "standard"
    PLATFORM_ADMIN = "platform_admin"


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or "@" not in normalized:
        raise ValueError("email_display must contain an email address.")
    return normalized


def normalize_slug(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
        raise ValueError("slug_normalized must contain lowercase letters, numbers, and hyphens only.")
    return normalized


class User(UUIDModel, TimestampedModel, Base):
    __tablename__ = "users"

    email_normalized: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    email_display: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default="active",
    )
    platform_role: Mapped[PlatformRole] = mapped_column(
        Enum(PlatformRole, name="platform_role", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=PlatformRole.STANDARD,
        server_default="standard",
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[OrganizationMembership]] = relationship(back_populates="user")
    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user")
    audit_events: Mapped[list[AuthAuditEvent]] = relationship(back_populates="user")


class Organization(UUIDModel, TimestampedModel, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug_normalized: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus, name="organization_status", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=OrganizationStatus.ACTIVE,
        server_default="active",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[OrganizationMembership]] = relationship(back_populates="organization")
    audit_events: Mapped[list[AuthAuditEvent]] = relationship(back_populates="organization")


class OrganizationMembership(UUIDModel, TimestampedModel, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_membership_user_organization"),
        Index("ix_membership_user_status", "user_id", "status"),
        Index("ix_membership_organization_status", "organization_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[OrganizationRole] = mapped_column(
        Enum(OrganizationRole, name="organization_role", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, name="membership_status", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=MembershipStatus.ACTIVE,
        server_default="active",
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class AuthSession(UUIDModel, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_session_user_active", "user_id", "revoked_at", "expires_at"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(100))
    ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    auth_method: Mapped[str] = mapped_column(String(50), nullable=False, default="password", server_default="password")

    user: Mapped[User] = relationship(back_populates="sessions")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="session", cascade="all, delete-orphan")
    audit_events: Mapped[list[AuthAuditEvent]] = relationship(back_populates="session")


class RefreshToken(UUIDModel, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
        Index("ix_refresh_token_session", "session_id"),
        Index("ix_refresh_token_family", "family_id"),
    )

    session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False)
    family_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    parent_token_id: Mapped[UUID | None] = mapped_column(ForeignKey("refresh_tokens.id", ondelete="SET NULL"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_token_id: Mapped[UUID | None] = mapped_column(ForeignKey("refresh_tokens.id", ondelete="SET NULL"))

    session: Mapped[AuthSession] = relationship(back_populates="refresh_tokens")
    parent_token: Mapped[RefreshToken | None] = relationship(foreign_keys=[parent_token_id], remote_side="RefreshToken.id")
    replacement_token: Mapped[RefreshToken | None] = relationship(foreign_keys=[replaced_by_token_id], remote_side="RefreshToken.id")


class AuthAuditEvent(UUIDModel, Base):
    __tablename__ = "auth_audit_events"
    __table_args__ = (
        Index("ix_auth_audit_event_user_occurred", "user_id", "occurred_at"),
        Index("ix_auth_audit_event_organization_occurred", "organization_id", "occurred_at"),
    )

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("auth_sessions.id", ondelete="SET NULL"))
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    reason_code: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default="{}")

    user: Mapped[User | None] = relationship(back_populates="audit_events")
    session: Mapped[AuthSession | None] = relationship(back_populates="audit_events")
    organization: Mapped[Organization | None] = relationship(back_populates="audit_events")


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def synchronize_user_email(_mapper, _connection, target: User) -> None:
    target.email_display = target.email_display.strip()
    target.email_normalized = normalize_email(target.email_display)


@event.listens_for(Organization, "before_insert")
@event.listens_for(Organization, "before_update")
def synchronize_organization_slug(_mapper, _connection, target: Organization) -> None:
    target.slug_normalized = normalize_slug(target.slug_normalized)


campaign_posts = Table(
    "campaign_posts",
    Base.metadata,
    Column("campaign_id", Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("post_id", Uuid, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
)


class Post(UUIDModel, TimestampedModel, Base):
    __tablename__ = "posts"

    canonical_url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="instagram")
    title: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaigns: Mapped[list[Campaign]] = relationship(secondary=campaign_posts, back_populates="posts")
    metric_snapshots: Mapped[list[PublicMetricSnapshot]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class Campaign(UUIDModel, TimestampedModel, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at", name="ck_campaign_period"),
    )

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    posts: Mapped[list[Post]] = relationship(secondary=campaign_posts, back_populates="campaigns")
    experiments: Mapped[list[Experiment]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class Experiment(UUIDModel, TimestampedModel, Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="ck_experiment_period"),
        UniqueConstraint("campaign_id", "name", name="uq_experiment_campaign_name"),
    )

    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    variable: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(100))
    evaluation_metrics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    success_criteria: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(ExperimentStatus, name="experiment_status", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=ExperimentStatus.DRAFT,
        server_default="draft",
    )

    campaign: Mapped[Campaign] = relationship(back_populates="experiments")
    distribution_events: Mapped[list[DistributionEvent]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    tracking_links: Mapped[list[TrackingLink]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class DistributionEvent(UUIDModel, TimestampedModel, Base):
    __tablename__ = "distribution_events"

    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(100), nullable=False)
    distributed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    experiment: Mapped[Experiment] = relationship(back_populates="distribution_events")


class MetricDefinition(UUIDModel, TimestampedModel, Base):
    __tablename__ = "metric_definitions"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[MetricClassification] = mapped_column(
        Enum(
            MetricClassification,
            name="metric_classification",
            values_callable=lambda classifications: [item.value for item in classifications],
        ),
        nullable=False,
    )

    snapshots: Mapped[list[PublicMetricSnapshot]] = relationship(back_populates="metric_definition")


class PublicMetricSnapshot(UUIDModel, TimestampedModel, Base):
    __tablename__ = "public_metric_snapshots"
    __table_args__ = (
        CheckConstraint("value >= 0", name="ck_snapshot_nonnegative_value"),
        UniqueConstraint("post_id", "metric_definition_id", "captured_at", name="uq_snapshot_capture"),
    )

    post_id: Mapped[UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    metric_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("metric_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    evidence_reference: Mapped[str | None] = mapped_column(String(2048))

    post: Mapped[Post] = relationship(back_populates="metric_snapshots")
    metric_definition: Mapped[MetricDefinition] = relationship(back_populates="snapshots")


class TrackingLink(UUIDModel, TimestampedModel, Base):
    __tablename__ = "tracking_links"

    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    destination_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    utm_source: Mapped[str] = mapped_column(String(100), nullable=False)
    utm_medium: Mapped[str] = mapped_column(String(100), nullable=False)
    utm_campaign: Mapped[str] = mapped_column(String(100), nullable=False)
    utm_content: Mapped[str | None] = mapped_column(String(255))
    utm_term: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")

    experiment: Mapped[Experiment] = relationship(back_populates="tracking_links")
    events: Mapped[list[TrackingEvent]] = relationship(
        back_populates="tracking_link", cascade="all, delete-orphan"
    )


class TrackingEvent(UUIDModel, Base):
    __tablename__ = "tracking_events"

    tracking_link_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracking_links.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, default="visit")
    referrer_domain: Mapped[str | None] = mapped_column(String(255))

    tracking_link: Mapped[TrackingLink] = relationship(back_populates="events")


class InfrastructureEvent(UUIDModel, Base):
    __tablename__ = "infrastructure_events"

    service: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[InfrastructureSeverity] = mapped_column(
        Enum(InfrastructureSeverity, name="infrastructure_severity", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
    )
    alert: Mapped[InfrastructureAlert | None] = relationship(back_populates="event", cascade="all, delete-orphan", uselist=False)


class InfrastructureAlert(UUIDModel, TimestampedModel, Base):
    __tablename__ = "infrastructure_alerts"

    event_id: Mapped[UUID] = mapped_column(ForeignKey("infrastructure_events.id", ondelete="CASCADE"), unique=True, nullable=False)
    is_acknowledged: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_resolved: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event: Mapped[InfrastructureEvent] = relationship(back_populates="alert")


class InfrastructureCheckRun(UUIDModel, Base):
    __tablename__ = "infrastructure_check_runs"
    __table_args__ = (Index("ix_infrastructure_check_runs_started_at", "started_at"),)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[SchedulerRunStatus] = mapped_column(
        Enum(SchedulerRunStatus, name="scheduler_run_status", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)


class InfrastructureSchedulerHeartbeat(Base):
    __tablename__ = "infrastructure_scheduler_heartbeat"

    scheduler_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
