from contextlib import contextmanager
import os
from urllib.parse import urlsplit

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.db.models import InfrastructureAlert, InfrastructureEvent
from app.db.session import get_session_factory
from app.infrastructure_events import record_transitions
from app.monitoring import ComponentStatus, SystemStatus, check_postgres, overall_status


@pytest.fixture(autouse=True)
def isolated_monitoring_database(monkeypatch):
    database_url = os.environ.get("TENANCY_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TENANCY_TEST_DATABASE_URL is required for monitoring integration tests.")
    database_name = urlsplit(database_url).path.lstrip("/")
    if database_name in {"growth_lab", "growth_lab_demo"} or not (database_name.startswith("test_") or database_name.endswith("_test")):
        pytest.fail("Monitoring tests require a dedicated PostgreSQL test database.")
    engine = create_engine(database_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(__import__(__name__), "get_session_factory", lambda: factory)
    yield
    engine.dispose()


class HealthyConnection:
    def execute(self, statement):
        return 1


class HealthyEngine:
    @contextmanager
    def connect(self):
        yield HealthyConnection()


class FailingEngine:
    @contextmanager
    def connect(self):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        yield


def test_postgres_check_reports_healthy() -> None:
    result = check_postgres(HealthyEngine())
    assert result.name == "postgresql"
    assert result.status == "healthy"
    assert result.checked_at.tzinfo is not None


def test_postgres_check_hides_connection_error_details() -> None:
    result = check_postgres(FailingEngine())
    assert result.status == "unavailable"
    assert result.message == "PostgreSQL connectivity check failed."
    assert "refused" not in result.message


def test_overall_status_is_degraded_when_a_component_fails() -> None:
    healthy = ComponentStatus(name="fastapi", status="healthy", checked_at=check_postgres(HealthyEngine()).checked_at, message="ok")
    unavailable = ComponentStatus(name="postgresql", status="unavailable", checked_at=healthy.checked_at, message="failed")
    assert overall_status([healthy, unavailable]) == "degraded"


def test_overall_status_is_unavailable_when_all_components_fail() -> None:
    failed = ComponentStatus(name="fastapi", status="unavailable", checked_at=check_postgres(HealthyEngine()).checked_at, message="failed")
    assert overall_status([failed]) == "unavailable"


def test_status_transitions_persist_once_and_recovery_acknowledges_alert() -> None:
    checked_at = check_postgres(HealthyEngine()).checked_at
    with get_session_factory()() as session:
        session.execute(delete(InfrastructureAlert))
        session.execute(delete(InfrastructureEvent))
        session.commit()
        failure = SystemStatus(status="degraded", previous_status="healthy", checked_at=checked_at, components=[ComponentStatus(name="fastapi", status="unavailable", previous_status="healthy", checked_at=checked_at, message="API unavailable."), ComponentStatus(name="postgresql", status="healthy", previous_status="healthy", checked_at=checked_at, message="ok")])
        assert len(record_transitions(session, failure)) == 2
        assert record_transitions(session, failure) == []
        assert session.scalar(select(InfrastructureAlert).where(InfrastructureAlert.is_acknowledged.is_(False))) is not None
        recovery = SystemStatus(status="healthy", previous_status="degraded", checked_at=checked_at, components=[ComponentStatus(name="fastapi", status="healthy", previous_status="unavailable", checked_at=checked_at, message="API responding."), ComponentStatus(name="postgresql", status="healthy", previous_status="healthy", checked_at=checked_at, message="ok")])
        assert len(record_transitions(session, recovery)) == 2
        recovered_alert = session.scalar(select(InfrastructureAlert))
        assert recovered_alert is not None
        assert recovered_alert.is_resolved is True
        assert recovered_alert.is_acknowledged is False
