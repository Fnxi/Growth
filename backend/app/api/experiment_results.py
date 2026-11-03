from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.metrics import Observation, variation
from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.api.scoped_loaders import get_experiment_for_org
from app.db.models import MetricDefinition, PublicMetricSnapshot, TrackingEvent, TrackingLink, campaign_posts
from app.db.session import get_db

router = APIRouter(tags=["experiment-results"])


@router.get("/organizations/{organization_id}/experiments/{experiment_id}/evaluation")
def evaluate_experiment(experiment_id: UUID, metric_name: str | None = None, context: OrgContext = Depends(require_org_roles(*CommercialRole)), session: Session = Depends(get_db)) -> dict[str, object]:
    experiment = get_experiment_for_org(session, context.organization.id, experiment_id)
    query = select(PublicMetricSnapshot, MetricDefinition.name).join(MetricDefinition).join(campaign_posts, PublicMetricSnapshot.post_id == campaign_posts.c.post_id).where(campaign_posts.c.campaign_id == experiment.campaign_id, campaign_posts.c.organization_id == context.organization.id)
    if metric_name:
        query = query.where(MetricDefinition.name == metric_name)
    rows = session.execute(query.order_by(PublicMetricSnapshot.captured_at)).all()
    grouped: dict[tuple[UUID, str], list[PublicMetricSnapshot]] = {}
    for snapshot, name in rows:
        grouped.setdefault((snapshot.post_id, name), []).append(snapshot)
    metrics = []
    for (post_id, name), snapshots in grouped.items():
        first, last = snapshots[0], snapshots[-1]
        result = variation(Observation(post_id, first.metric_definition_id, first.value, first.captured_at), Observation(post_id, last.metric_definition_id, last.value, last.captured_at))
        metrics.append({"post_id": str(post_id), "metric_name": name, "initial": str(first.value), "final": str(last.value), "absolute_change": str(result.absolute_change) if result.absolute_change is not None else None, "percentage_change": str(result.percentage_change) if result.percentage_change is not None else None, "attribution": "campaign_shared", "limitations": list(result.limitations)})
    clicks = session.scalar(select(func.count()).select_from(TrackingEvent).join(TrackingLink).where(TrackingLink.experiment_id == experiment_id, TrackingEvent.event_type == "click")) or 0
    return {"experiment_id": str(experiment_id), "status": experiment.status, "distribution_actions": len(experiment.distribution_events), "clicks_registered": clicks, "metrics": metrics, "limitations": ["Observed snapshots belong to campaign posts and may be shared by multiple experiments in that campaign; they are not exclusive experiment results.", "Observed public metrics and first-party clicks are reported separately. Results do not establish causality or unique people."]}
