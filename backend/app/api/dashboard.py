from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.api.scoped_loaders import get_post_for_org
from app.db.models import Campaign, Experiment, MetricClassification, MetricDefinition, Post, PublicMetricSnapshot, TrackingEvent, TrackingLink
from app.db.session import get_db

router = APIRouter(tags=["dashboard"])
READ_ROLES = tuple(CommercialRole)


@router.get("/organizations/{organization_id}/dashboard/summary")
def dashboard_summary(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db)) -> dict[str, object]:
    organization_id = context.organization.id
    recent = session.scalars(select(Experiment).join(Campaign).where(Campaign.organization_id == organization_id).order_by(Experiment.created_at.desc()).limit(5))
    return {
        "campaigns": session.scalar(select(func.count()).select_from(Campaign).where(Campaign.organization_id == organization_id)) or 0,
        "experiments": session.scalar(select(func.count()).select_from(Experiment).join(Campaign).where(Campaign.organization_id == organization_id)) or 0,
        "posts": session.scalar(select(func.count()).select_from(Post).where(Post.organization_id == organization_id)) or 0,
        "clicks_registered": session.scalar(select(func.count()).select_from(TrackingEvent).join(TrackingLink).join(Experiment).join(Campaign).where(TrackingEvent.event_type == "click", Campaign.organization_id == organization_id)) or 0,
        "recent_experiments": [{"id": str(item.id), "name": item.name, "campaign_id": str(item.campaign_id), "starts_at": item.starts_at} for item in recent],
        "limitations": ["Clicks are first-party events, not reach, impressions, or unique people."],
    }


@router.get("/organizations/{organization_id}/analytics/observed-metrics")
def observed_metrics(metric_name: str, post_id: UUID | None = None, context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db)) -> dict[str, object]:
    organization_id = context.organization.id
    query = select(PublicMetricSnapshot).join(MetricDefinition).join(Post).where(MetricDefinition.name == metric_name, MetricDefinition.classification == MetricClassification.OBSERVED, Post.organization_id == organization_id)
    if post_id:
        get_post_for_org(session, organization_id, post_id)
        query = query.where(PublicMetricSnapshot.post_id == post_id)
    snapshots = session.scalars(query.order_by(PublicMetricSnapshot.captured_at)).all()
    return {
        "metric_name": metric_name,
        "points": [{"post_id": str(item.post_id), "value": str(item.value), "captured_at": item.captured_at} for item in snapshots],
        "limitations": ["Observed public counts are not Instagram reach or impressions."],
    }
