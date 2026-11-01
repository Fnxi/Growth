from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import InfrastructureAlert, InfrastructureCheckRun, InfrastructureEvent, PublicMetricSnapshot
from app.operational_intelligence.engine import AnalysisItem, check_duration_anomalies, metric_change_anomalies, metric_data_limitations, recurrent_event_anomalies


class OperationalIntelligenceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze(self, session: Session) -> list[AnalysisItem]:
        series = self._metric_series(session)
        runs = list(session.scalars(select(InfrastructureCheckRun).order_by(InfrastructureCheckRun.started_at)))
        event_rows = session.execute(select(InfrastructureEvent, InfrastructureAlert).outerjoin(InfrastructureAlert, InfrastructureAlert.event_id == InfrastructureEvent.id).where(InfrastructureEvent.new_status != "healthy").order_by(InfrastructureEvent.occurred_at.desc()).limit(50)).all()
        results = metric_change_anomalies(series, self.settings.intelligence_metric_change_threshold_percent)
        results += check_duration_anomalies([(str(item.id), item.started_at, item.duration_ms, item.status.value) for item in runs], self.settings.intelligence_check_duration_threshold_percent)
        results += recurrent_event_anomalies([(str(event.id), event.service, event.occurred_at, bool(alert and not alert.is_resolved)) for event, alert in event_rows], self.settings.intelligence_recurrent_event_threshold)
        priority = {"critical": 0, "warning": 1, "info": 2}
        return sorted(results, key=lambda item: (priority.get(item.severity, 9), item.category, item.id))

    @staticmethod
    def _metric_series(session: Session):
        series = defaultdict(list)
        for item in session.scalars(select(PublicMetricSnapshot).order_by(PublicMetricSnapshot.captured_at)):
            series[f"{item.post_id}:{item.metric_definition_id}"].append((item.captured_at, item.value))
        return series

    def summary(self, session: Session) -> dict[str, object]:
        anomalies = self.analyze(session)
        grouped = {}
        for item in anomalies:
            service = item.id.split(":", 1)[1] if item.category == "recurrent_infrastructure_event" else None
            key = (item.category, service)
            grouped.setdefault(key, []).append(item)
        priority = {"critical": 0, "warning": 1, "info": 2}
        recommendations = []
        for (category, service), items in sorted(grouped.items(), key=lambda pair: (priority.get(pair[1][0].severity, 9), pair[0])):
            evidence = sorted({reference for item in items for reference in item.evidence})
            limitations = sorted({limitation for item in items for limitation in item.limitations})
            recommendations.append({"priority": items[0].severity, "recommendation": f"Review {category}" + (f" for {service}." if service else "."), "evidence": evidence, "limitations": limitations})
        limitations = metric_data_limitations(self._metric_series(session))
        return {"anomalies": anomalies, "trends": [item for item in anomalies if item.category == "metric_change"], "findings": anomalies, "recommendations": recommendations, "data_limitations": limitations, "limitations": ["Relevant changes are threshold-based signals, not a complete trend analysis.", "Results are deterministic checks and do not establish causality.", *[item.description for item in limitations] ]}
