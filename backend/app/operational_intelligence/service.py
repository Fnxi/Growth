from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Post, PublicMetricSnapshot
from app.operational_intelligence.engine import AnalysisItem, metric_change_anomalies, metric_data_limitations


class OperationalIntelligenceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze(self, session: Session, organization_id: UUID) -> list[AnalysisItem]:
        series = self._metric_series(session, organization_id)
        results = metric_change_anomalies(series, self.settings.intelligence_metric_change_threshold_percent)
        priority = {"critical": 0, "warning": 1, "info": 2}
        return sorted(results, key=lambda item: (priority.get(item.severity, 9), item.category, item.id))

    @staticmethod
    def _metric_series(session: Session, organization_id: UUID):
        series = defaultdict(list)
        for item in session.scalars(select(PublicMetricSnapshot).join(Post).where(Post.organization_id == organization_id).order_by(PublicMetricSnapshot.captured_at)):
            series[f"{item.post_id}:{item.metric_definition_id}"].append((item.captured_at, item.value))
        return series

    def summary(self, session: Session, organization_id: UUID) -> dict[str, object]:
        anomalies = self.analyze(session, organization_id)
        grouped = {}
        for item in anomalies:
            key = (item.category, None)
            grouped.setdefault(key, []).append(item)
        priority = {"critical": 0, "warning": 1, "info": 2}
        recommendations = []
        for (category, service), items in sorted(grouped.items(), key=lambda pair: (priority.get(pair[1][0].severity, 9), pair[0])):
            evidence = sorted({reference for item in items for reference in item.evidence})
            limitations = sorted({limitation for item in items for limitation in item.limitations})
            recommendations.append({"priority": items[0].severity, "recommendation": f"Review {category}" + (f" for {service}." if service else "."), "evidence": evidence, "limitations": limitations})
        limitations = metric_data_limitations(self._metric_series(session, organization_id))
        return {"anomalies": anomalies, "trends": [item for item in anomalies if item.category == "metric_change"], "findings": anomalies, "recommendations": recommendations, "data_limitations": limitations, "limitations": ["Relevant changes are threshold-based signals, not a complete trend analysis.", "Results are deterministic checks and do not establish causality.", *[item.description for item in limitations] ]}
