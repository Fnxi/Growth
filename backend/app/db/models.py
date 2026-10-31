from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
    UniqueConstraint,
    func,
    JSON,
)
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
