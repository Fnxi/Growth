from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Campaign, Experiment, MetricClassification, MetricDefinition, Post, PublicMetricSnapshot, TrackingEvent
from app.db.session import get_db

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary")
def dashboard_summary(session: Session = Depends(get_db)) -> dict[str, object]:
    recent = session.scalars(select(Experiment).order_by(Experiment.created_at.desc()).limit(5))
    return {
        "campaigns": session.scalar(select(func.count()).select_from(Campaign)) or 0,
        "experiments": session.scalar(select(func.count()).select_from(Experiment)) or 0,
        "posts": session.scalar(select(func.count()).select_from(Post)) or 0,
        "clicks_registered": session.scalar(select(func.count()).select_from(TrackingEvent).where(TrackingEvent.event_type == "click")) or 0,
        "recent_experiments": [{"id": str(item.id), "name": item.name, "campaign_id": str(item.campaign_id), "starts_at": item.starts_at} for item in recent],
        "limitations": ["Clicks are first-party events, not reach, impressions, or unique people."],
    }


@router.get("/analytics/observed-metrics")
def observed_metrics(metric_name: str, post_id: UUID | None = None, session: Session = Depends(get_db)) -> dict[str, object]:
    query = select(PublicMetricSnapshot).join(MetricDefinition).where(MetricDefinition.name == metric_name, MetricDefinition.classification == MetricClassification.OBSERVED)
    if post_id:
        query = query.where(PublicMetricSnapshot.post_id == post_id)
    snapshots = session.scalars(query.order_by(PublicMetricSnapshot.captured_at)).all()
    return {
        "metric_name": metric_name,
        "points": [{"post_id": str(item.post_id), "value": str(item.value), "captured_at": item.captured_at} for item in snapshots],
        "limitations": ["Observed public counts are not Instagram reach or impressions."],
    }
