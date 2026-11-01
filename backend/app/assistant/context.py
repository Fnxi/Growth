import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Campaign, Experiment, InfrastructureAlert, InfrastructureCheckRun, InfrastructureEvent, MetricDefinition, PublicMetricSnapshot, TrackingEvent, TrackingLink
from app.monitoring import inspect_system
from app.operational_intelligence.service import OperationalIntelligenceService
from app.config import get_settings


class ContextBuilder:
    """Builds bounded, read-only operational facts; database text remains untrusted data."""

    def __init__(self, max_characters: int) -> None:
        self.max_characters = max_characters

    def build(self, session: Session, question: str) -> tuple[str, list[str]]:
        system = inspect_system()
        events = list(session.scalars(select(InfrastructureEvent).order_by(InfrastructureEvent.occurred_at.desc()).limit(10)))
        alerts = list(session.scalars(select(InfrastructureAlert).order_by(InfrastructureAlert.created_at.desc()).limit(10)))
        runs = list(session.scalars(select(InfrastructureCheckRun).order_by(InfrastructureCheckRun.started_at.desc()).limit(10)))
        facts: dict[str, object] = {
            "system": {"status": system.status, "components": [{"name": item.name, "status": item.status} for item in system.components]},
            "events": [{"id": str(item.id), "service": item.service, "from": item.previous_status, "to": item.new_status, "severity": item.severity.value, "at": item.occurred_at.isoformat()} for item in events],
            "alerts": [{"id": str(item.id), "event_id": str(item.event_id), "acknowledged": item.is_acknowledged, "resolved": item.is_resolved, "created_at": item.created_at.isoformat()} for item in alerts],
            "checks": [{"id": str(item.id), "status": item.status.value, "started_at": item.started_at.isoformat(), "duration_ms": item.duration_ms} for item in runs],
        }
        references = [f"event:{item.id}" for item in events] + [f"alert:{item.id}" for item in alerts] + [f"check:{item.id}" for item in runs]
        if any(term in question.lower() for term in ("anomal", "tendencia", "patrón", "patron", "inteligencia", "prioridad")):
            analysis = OperationalIntelligenceService(get_settings()).analyze(session)
            facts["operational_intelligence"] = [{"id": item.id, "category": item.category, "severity": item.severity, "observed_value": item.observed_value, "baseline": item.baseline, "evidence": list(item.evidence), "limitations": list(item.limitations)} for item in analysis]
            references.extend(item.id for item in analysis)
        terms = question.lower()
        if any(term in terms for term in ("campaña", "experimento", "métrica", "metrica", "tracking", "clic")):
            experiments = list(session.scalars(select(Experiment).order_by(Experiment.updated_at.desc()).limit(10)))
            campaigns = list(session.scalars(select(Campaign).order_by(Campaign.updated_at.desc()).limit(10)))
            facts["experiments"] = [{"id": str(item.id), "campaign_id": str(item.campaign_id), "name": item.name, "status": item.status.value, "starts_at": item.starts_at.isoformat(), "ends_at": item.ends_at.isoformat() if item.ends_at else None} for item in experiments]
            facts["campaigns"] = [{"id": str(item.id), "name": item.name, "starts_at": item.starts_at.isoformat() if item.starts_at else None, "ends_at": item.ends_at.isoformat() if item.ends_at else None} for item in campaigns]
            references.extend(f"experiment:{item.id}" for item in experiments)
            references.extend(f"campaign:{item.id}" for item in campaigns)
        if any(term in terms for term in ("métrica", "metrica", "observada", "clic", "tracking")):
            snapshots = session.execute(select(PublicMetricSnapshot, MetricDefinition.name).join(MetricDefinition).order_by(PublicMetricSnapshot.captured_at.desc()).limit(20)).all()
            facts["metrics"] = [{"snapshot_id": str(item.id), "metric": name, "value": str(item.value), "captured_at": item.captured_at.isoformat()} for item, name in snapshots]
            links = list(session.scalars(select(TrackingLink).order_by(TrackingLink.created_at.desc()).limit(10)))
            facts["tracking"] = [{"link_id": str(item.id), "experiment_id": str(item.experiment_id), "active": item.is_active, "source": item.utm_source, "medium": item.utm_medium} for item in links]
            references.extend(f"metric:{item.id}" for item, _ in snapshots)
            references.extend(f"tracking_link:{item.id}" for item in links)
        context = json.dumps(facts, ensure_ascii=True, separators=(",", ":"))
        return context[: self.max_characters], references[:20]
