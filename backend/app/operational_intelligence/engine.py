from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class AnalysisItem:
    id: str
    category: str
    severity: str
    description: str
    observed_value: str | None
    baseline: str | None
    detected_at: datetime
    evidence: tuple[str, ...]
    limitations: tuple[str, ...]


def metric_change_anomalies(series: dict[str, list[tuple[datetime, Decimal]]], threshold_percent: int) -> list[AnalysisItem]:
    findings = []
    for key, values in series.items():
        ordered = sorted((item for item in values if item[1] >= 0), key=lambda item: item[0])
        if len(ordered) < 3:
            continue
        _, previous = ordered[-2]
        observed_at, current = ordered[-1]
        if previous <= 0 or current < 0:
            continue
        change = ((current - previous) / previous) * Decimal("100")
        if abs(change) >= threshold_percent:
            direction = "increased" if change > 0 else "decreased"
            findings.append(AnalysisItem(f"metric-change:{key}:{observed_at.isoformat()}", "metric_change", "warning", f"Observed metric {direction} by {change:.1f}% between the two latest observations.", str(current), str(previous), observed_at, (f"metric:{key}",), ("Observed public metrics are not reach, impressions, or causal evidence.",)))
    return findings


def metric_data_limitations(series: dict[str, list[tuple[datetime, Decimal]]]) -> list[AnalysisItem]:
    results = []
    for key, values in series.items():
        ordered = sorted(values, key=lambda item: item[0])
        if len(ordered) >= 2 and ordered[-2][1] <= 0:
            results.append(AnalysisItem(f"metric-baseline:{key}:{ordered[-1][0].isoformat()}", "metric_baseline_unavailable", "info", "Percentage variation was not calculated because the reference value is zero or non-positive.", str(ordered[-1][1]), str(ordered[-2][1]), ordered[-1][0], (f"metric:{key}",), ("A conventional percentage change requires a positive reference value.",)))
    return results


def check_duration_anomalies(runs: list[tuple[str, datetime, int | None, str]], threshold_percent: int) -> list[AnalysisItem]:
    completed = sorted((item for item in runs if item[2] is not None and item[2] >= 0 and item[3] in {"success", "degraded"}), key=lambda item: (item[1], item[0]))
    if len(completed) < 3:
        return []
    latest = completed[-1]
    baseline = sum(item[2] or 0 for item in completed[:-1]) / len(completed[:-1])
    if baseline <= 0 or (latest[2] or 0) < baseline * (1 + threshold_percent / 100):
        return []
    return [AnalysisItem(f"check-duration:{latest[0]}", "check_duration", "warning", "Latest infrastructure check duration exceeded the recent baseline.", str(latest[2]), f"{baseline:.0f}", latest[1], (f"check:{latest[0]}",), ("Duration alone does not identify the cause.",))]


def recurrent_event_anomalies(events: list[tuple[str, str, datetime, bool]], threshold: int) -> list[AnalysisItem]:
    counts: dict[str, list[tuple[str, datetime, bool]]] = {}
    for event_id, service, occurred_at, active in events:
        if any(event_id == item[0] for item in counts.get(service, [])):
            continue
        counts.setdefault(service, []).append((event_id, occurred_at, active))
    results = []
    for service, items in counts.items():
        if len(items) >= threshold:
            active = [item for item in items if item[2]]
            severity = "critical" if active else "warning"
            description = f"{len(items)} non-healthy infrastructure transitions were recorded for {service}."
            if not active:
                description += " All corresponding alerts are resolved; this is historical recurrence, not an active condition."
            results.append(AnalysisItem(f"recurrent-events:{service}", "recurrent_infrastructure_event", severity, description, str(len(items)), str(threshold), max(item[1] for item in items), tuple(f"event:{item[0]}" for item in items), ("Repeated transitions indicate recurrence, not a proven root cause.",)))
    return results
