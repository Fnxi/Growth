from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api import operational_intelligence as intelligence_api
from app.operational_intelligence.engine import check_duration_anomalies, metric_change_anomalies, recurrent_event_anomalies
from app.main import app


def test_metric_anomaly_requires_three_observations_and_threshold() -> None:
    now = datetime.now(timezone.utc)
    assert metric_change_anomalies({"metric": [(now, Decimal("10")), (now + timedelta(days=1), Decimal("20"))]}, 30) == []
    results = metric_change_anomalies({"metric": [(now, Decimal("10")), (now + timedelta(days=1), Decimal("11")), (now + timedelta(days=2), Decimal("20"))]}, 30)
    assert len(results) == 1
    assert results[0].severity == "warning"
    assert "metric:metric" in results[0].evidence


def test_metric_ignores_negative_values_and_zero_baseline() -> None:
    now = datetime.now(timezone.utc)
    assert metric_change_anomalies({"metric": [(now, Decimal("-1")), (now + timedelta(days=1), Decimal("10")), (now + timedelta(days=2), Decimal("30"))]}, 30) == []
    assert metric_change_anomalies({"metric": [(now, Decimal("10")), (now + timedelta(days=1), Decimal("0")), (now + timedelta(days=2), Decimal("5"))]}, 30) == []


def test_check_duration_anomaly_uses_recent_baseline() -> None:
    now = datetime.now(timezone.utc)
    results = check_duration_anomalies([("a", now, 10, "success"), ("b", now + timedelta(minutes=1), 12, "success"), ("c", now + timedelta(minutes=2), 30, "success")], 50)
    assert len(results) == 1
    assert results[0].baseline == "11"


def test_check_duration_excludes_failed_incomplete_and_orders_input() -> None:
    now = datetime.now(timezone.utc)
    runs = [("z", now + timedelta(minutes=3), 100, "failed"), ("c", now + timedelta(minutes=2), 30, "success"), ("a", now, 10, "success"), ("b", now + timedelta(minutes=1), None, "success"), ("d", now + timedelta(minutes=2), 31, "degraded")]
    results = check_duration_anomalies(runs, 50)
    assert results[0].id == "check-duration:d"


def test_recurrent_events_are_classified_critical() -> None:
    now = datetime.now(timezone.utc)
    results = recurrent_event_anomalies([("a", "postgresql", now, True), ("b", "postgresql", now + timedelta(minutes=1), False), ("c", "postgresql", now + timedelta(minutes=2), False)], 3)
    assert len(results) == 1
    assert results[0].severity == "critical"


def test_resolved_or_duplicate_events_are_historical_only() -> None:
    now = datetime.now(timezone.utc)
    results = recurrent_event_anomalies([("a", "postgresql", now, False), ("a", "postgresql", now, False), ("b", "postgresql", now + timedelta(minutes=1), False), ("c", "postgresql", now + timedelta(minutes=2), False)], 3)
    assert len(results) == 1
    assert results[0].severity == "warning"
    assert "historical recurrence" in results[0].description


def test_operational_intelligence_endpoints_are_read_only() -> None:
    with TestClient(app) as client:
        for path in ("/operational-intelligence/anomalies", "/operational-intelligence/trends", "/operational-intelligence/findings", "/operational-intelligence/recommendations", "/operational-intelligence/summary"):
            assert client.get(path).status_code == 200


def test_operational_intelligence_hides_database_errors() -> None:
    class FailingService:
        def summary(self, _session):
            raise SQLAlchemyError("SELECT password FROM private_table")

    app.dependency_overrides[intelligence_api.get_service] = lambda: FailingService()
    try:
        with TestClient(app) as client:
            response = client.get("/operational-intelligence/summary")
        assert response.status_code == 503
        assert response.json()["detail"] == "Operational intelligence data is temporarily unavailable."
        assert "SELECT" not in response.text
        assert "password" not in response.text
    finally:
        app.dependency_overrides.clear()
