from contextlib import contextmanager

from sqlalchemy.exc import OperationalError
from sqlalchemy import delete, select

from app.db.models import InfrastructureAlert, InfrastructureEvent
from app.db.session import get_session_factory
from app.infrastructure_events import record_transitions
from app.monitoring import ComponentStatus, SystemStatus, check_postgres, overall_status


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
