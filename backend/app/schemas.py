from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.db.models import ExperimentStatus, InfrastructureSeverity, MetricClassification


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PeriodModel(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "PeriodModel":
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("ends_at must not be before starts_at")
        return self


class PostCreate(BaseModel):
    canonical_url: HttpUrl
    platform: str = Field(default="instagram", min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None


class PostUpdate(BaseModel):
    canonical_url: HttpUrl | None = None
    platform: str | None = Field(default=None, min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None


class PostRead(ORMModel):
    id: UUID
    canonical_url: str
    platform: str
    title: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignCreate(PeriodModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    post_ids: list[UUID] = Field(default_factory=list)


class CampaignUpdate(PeriodModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    post_ids: list[UUID] | None = None


class CampaignRead(ORMModel):
    id: UUID
    name: str
    description: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    posts: list[PostRead]
    created_at: datetime
    updated_at: datetime


class ExperimentCreate(PeriodModel):
    campaign_id: UUID
    name: str = Field(min_length=1, max_length=120)
    hypothesis: str = Field(min_length=1)
    variable: str = Field(min_length=1, max_length=255)
    method: str = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime | None = None
    result: str | None = None
    conclusion: str | None = None
    objective: str | None = None
    channel: str | None = Field(default=None, max_length=100)
    evaluation_metrics: list[str] = Field(default_factory=list)
    success_criteria: str | None = None


class ExperimentUpdate(PeriodModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    hypothesis: str | None = Field(default=None, min_length=1)
    variable: str | None = Field(default=None, min_length=1, max_length=255)
    method: str | None = Field(default=None, min_length=1)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    result: str | None = None
    conclusion: str | None = None
    objective: str | None = None
    channel: str | None = Field(default=None, max_length=100)
    evaluation_metrics: list[str] | None = None
    success_criteria: str | None = None


class ExperimentRead(ORMModel):
    id: UUID
    campaign_id: UUID
    name: str
    hypothesis: str
    variable: str
    method: str
    starts_at: datetime
    ends_at: datetime | None
    result: str | None
    conclusion: str | None
    created_at: datetime
    updated_at: datetime
    objective: str | None
    channel: str | None
    evaluation_metrics: list[str]
    success_criteria: str | None
    status: ExperimentStatus


class ExperimentStatusUpdate(BaseModel):
    status: ExperimentStatus
    ended_at: datetime | None = None


class InfrastructureEventRead(ORMModel):
    id: UUID
    service: str
    event_type: str
    previous_status: str | None
    new_status: str
    occurred_at: datetime
    description: str
    severity: InfrastructureSeverity


class InfrastructureAlertRead(ORMModel):
    id: UUID
    event_id: UUID
    is_acknowledged: bool
    acknowledged_at: datetime | None
    is_resolved: bool
    resolved_at: datetime | None
    created_at: datetime
    event: InfrastructureEventRead


class MetricDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    category: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    limitations: str = Field(min_length=1)
    classification: MetricClassification


class MetricDefinitionUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=100)
    source: str | None = Field(default=None, min_length=1, max_length=100)
    limitations: str | None = Field(default=None, min_length=1)
    classification: MetricClassification | None = None


class MetricDefinitionRead(ORMModel):
    id: UUID
    name: str
    category: str
    source: str
    limitations: str
    classification: MetricClassification
    created_at: datetime
    updated_at: datetime


class PublicMetricSnapshotCreate(BaseModel):
    post_id: UUID
    metric_definition_id: UUID
    value: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    captured_at: datetime
    evidence_reference: str | None = Field(default=None, max_length=2048)


class PublicMetricSnapshotRead(ORMModel):
    id: UUID
    post_id: UUID
    metric_definition_id: UUID
    value: Decimal
    captured_at: datetime
    evidence_reference: str | None
    created_at: datetime
    updated_at: datetime


class DistributionEventCreate(BaseModel):
    experiment_id: UUID
    channel: str = Field(min_length=1, max_length=100)
    distributed_at: datetime
    notes: str | None = None


class DistributionEventRead(ORMModel):
    id: UUID
    experiment_id: UUID
    channel: str
    distributed_at: datetime
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TrackingLinkCreate(BaseModel):
    experiment_id: UUID
    destination_url: HttpUrl
    utm_source: str = Field(min_length=1, max_length=100)
    utm_medium: str = Field(min_length=1, max_length=100)
    utm_campaign: str = Field(min_length=1, max_length=100)
    utm_content: str | None = Field(default=None, max_length=255)


class TrackingLinkRead(ORMModel):
    id: UUID
    experiment_id: UUID
    campaign_id: UUID
    code: str
    destination_url: str
    tracking_url: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str | None
    is_active: bool
    created_at: datetime


class TrackingLinkUpdate(BaseModel):
    is_active: bool
