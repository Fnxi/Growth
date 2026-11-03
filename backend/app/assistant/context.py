import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Campaign, Experiment, MetricDefinition, Post, PublicMetricSnapshot, TrackingLink


class ContextBuilder:
    """Build bounded commercial facts for exactly one authorized organization."""

    def __init__(self, max_characters: int) -> None:
        self.max_characters = max_characters

    def build(self, session: Session, organization_id: UUID, question: str) -> tuple[str, list[str]]:
        facts: dict[str, object] = {}
        references: list[str] = []
        terms = question.lower()
        if any(term in terms for term in ("campaña", "experimento", "métrica", "metrica", "tracking", "clic")):
            experiments = list(session.scalars(select(Experiment).join(Campaign).where(Campaign.organization_id == organization_id).order_by(Experiment.updated_at.desc()).limit(10)))
            campaigns = list(session.scalars(select(Campaign).where(Campaign.organization_id == organization_id).order_by(Campaign.updated_at.desc()).limit(10)))
            facts["experiments"] = [{"id": str(item.id), "campaign_id": str(item.campaign_id), "name": item.name, "status": item.status.value, "starts_at": item.starts_at.isoformat(), "ends_at": item.ends_at.isoformat() if item.ends_at else None} for item in experiments]
            facts["campaigns"] = [{"id": str(item.id), "name": item.name, "starts_at": item.starts_at.isoformat() if item.starts_at else None, "ends_at": item.ends_at.isoformat() if item.ends_at else None} for item in campaigns]
            references.extend(f"experiment:{item.id}" for item in experiments)
            references.extend(f"campaign:{item.id}" for item in campaigns)
        if any(term in terms for term in ("métrica", "metrica", "observada", "clic", "tracking")):
            snapshots = session.execute(select(PublicMetricSnapshot, MetricDefinition.name).join(MetricDefinition).join(Post).where(Post.organization_id == organization_id).order_by(PublicMetricSnapshot.captured_at.desc()).limit(20)).all()
            facts["metrics"] = [{"snapshot_id": str(item.id), "metric": name, "value": str(item.value), "captured_at": item.captured_at.isoformat()} for item, name in snapshots]
            links = list(session.scalars(select(TrackingLink).join(Experiment).join(Campaign).where(Campaign.organization_id == organization_id).order_by(TrackingLink.created_at.desc()).limit(10)))
            facts["tracking"] = [{"link_id": str(item.id), "experiment_id": str(item.experiment_id), "active": item.is_active, "source": item.utm_source, "medium": item.utm_medium} for item in links]
            references.extend(f"metric:{item.id}" for item, _ in snapshots)
            references.extend(f"tracking_link:{item.id}" for item in links)
        context = json.dumps(facts, ensure_ascii=True, separators=(",", ":"))
        return context[: self.max_characters], references[:20]
