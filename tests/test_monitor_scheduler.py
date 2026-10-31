from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from types import SimpleNamespace

from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

import app.infrastructure_events as infrastructure_events
import app.monitor_scheduler as monitor_scheduler
from app.api import system
from app.db.models import InfrastructureCheckRun, InfrastructureEvent, InfrastructureSchedulerHeartbeat, SchedulerRunStatus
from app.db.session import get_engine, get_session_factory
from app.monitor_scheduler import InfrastructureScheduler, SCHEDULER_LOCK_ID, SCHEDULER_NAME


def _clear_scheduler_data() -> None:
    with get_session_factory()() as session:
        session.execute(delete(InfrastructureCheckRun))
        session.execute(delete(InfrastructureEvent))
        session.execute(delete(InfrastructureSchedulerHeartbeat))
        session.commit()


def test_scheduler_persists_runs_and_does_not_duplicate_transitions() -> None:
    _clear_scheduler_data()
    infrastructure_events._last_component_statuses.clear()
    infrastructure_events._last_component_statuses["postgresql"] = "unavailable"
    infrastructure_events._last_system_status = "degraded"
    scheduler = InfrastructureScheduler(interval_seconds=10)

    assert scheduler.run_once() is True
    assert scheduler.run_once() is True

    with get_session_factory()() as session:
        runs = list(session.scalars(select(InfrastructureCheckRun).order_by(InfrastructureCheckRun.started_at)))
        events = list(session.scalars(select(InfrastructureEvent).order_by(InfrastructureEvent.occurred_at)))
    assert len(runs) == 2
    assert all(run.status == SchedulerRunStatus.SUCCESS for run in runs)
    assert len(events) == 2


def test_scheduler_skips_when_another_instance_holds_postgres_lock() -> None:
    _clear_scheduler_data()
    with get_session_factory()() as lock_session:
        assert lock_session.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": SCHEDULER_LOCK_ID}).scalar()
        assert InfrastructureScheduler(interval_seconds=10).run_once() is False
        lock_session.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": SCHEDULER_LOCK_ID})

    with get_session_factory()() as session:
        assert session.scalar(select(InfrastructureCheckRun)) is None


def test_two_scheduler_instances_cannot_run_the_check_concurrently(monkeypatch) -> None:
    _clear_scheduler_data()
    entered = Event()
    release = Event()
    calls = []

    def slow_check(_session):
        calls.append("check")
        entered.set()
        assert release.wait(timeout=5)
        return type("Result", (), {"status": "healthy"})()

    monkeypatch.setattr(monitor_scheduler, "run_infrastructure_check", slow_check)
    first = InfrastructureScheduler(interval_seconds=10)
    worker = Thread(target=first.run_once)
    worker.start()
    assert entered.wait(timeout=5)
    assert InfrastructureScheduler(interval_seconds=10).run_once() is False
    release.set()
    worker.join(timeout=5)

    with get_session_factory()() as session:
        assert len(list(session.scalars(select(InfrastructureCheckRun)))) == 1
    assert calls == ["check"]


def test_postgres_releases_advisory_lock_when_connection_closes() -> None:
    connection = get_engine().connect()
    assert connection.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": SCHEDULER_LOCK_ID}).scalar()
    connection.invalidate()
    connection.close()
    with get_engine().connect() as replacement:
        assert replacement.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": SCHEDULER_LOCK_ID}).scalar()
        replacement.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": SCHEDULER_LOCK_ID})


def test_scheduler_records_failure_and_recovers(monkeypatch) -> None:
    _clear_scheduler_data()
    scheduler = InfrastructureScheduler(interval_seconds=10)

    def raise_check(_session):
        raise RuntimeError("connection details must not be stored")

    monkeypatch.setattr(monitor_scheduler, "run_infrastructure_check", raise_check)
    assert scheduler.run_once() is False
    with get_session_factory()() as session:
        failed = session.scalar(select(InfrastructureCheckRun))
    assert failed is not None
    assert failed.status == SchedulerRunStatus.FAILED
    assert "connection details" not in failed.message

    monkeypatch.setattr(monitor_scheduler, "run_infrastructure_check", lambda _session: type("Result", (), {"status": "healthy"})())
    assert InfrastructureScheduler(interval_seconds=10).run_once() is True
    with get_session_factory()() as session:
        statuses = list(session.scalars(select(InfrastructureCheckRun.status).order_by(InfrastructureCheckRun.started_at)))
    assert statuses == [SchedulerRunStatus.FAILED, SchedulerRunStatus.SUCCESS]


def test_scheduler_continues_after_database_unavailability() -> None:
    @contextmanager
    def unavailable_session():
        raise OperationalError("SELECT 1", {}, Exception("database unavailable"))
        yield

    assert InfrastructureScheduler(session_factory=unavailable_session, interval_seconds=10).run_once() is False


def test_scheduler_loop_uses_the_configured_interval(monkeypatch) -> None:
    scheduler = InfrastructureScheduler(interval_seconds=17)
    monkeypatch.setattr(scheduler, "run_once", lambda: True)

    def stop_after_first_sleep(seconds: int) -> None:
        assert seconds == 17
        raise StopIteration

    try:
        scheduler.run_forever(sleep=stop_after_first_sleep)
    except StopIteration:
        pass


def test_scheduler_status_uses_heartbeat_not_only_configuration(monkeypatch) -> None:
    _clear_scheduler_data()
    settings = SimpleNamespace(monitoring_scheduler_enabled=False, monitoring_check_interval_seconds=10)
    monkeypatch.setattr(system, "get_settings", lambda: settings)
    now = datetime.now(timezone.utc)
    with get_session_factory()() as session:
        assert system.scheduler_status(session).status == "disabled"
        settings.monitoring_scheduler_enabled = True
        assert system.scheduler_status(session).status == "not_started"
        session.add(InfrastructureSchedulerHeartbeat(scheduler_name=SCHEDULER_NAME, last_heartbeat_at=now))
        session.commit()
        assert system.scheduler_status(session).status == "running"
        heartbeat = session.get(InfrastructureSchedulerHeartbeat, SCHEDULER_NAME)
        assert heartbeat is not None
        heartbeat.last_heartbeat_at = now - timedelta(seconds=31)
        session.commit()
        assert system.scheduler_status(session).status == "inactive"
        heartbeat.last_heartbeat_at = now
        heartbeat.stopped_at = now
        session.commit()
        assert system.scheduler_status(session).status == "stopped"
        heartbeat.stopped_at = None
        session.add(InfrastructureCheckRun(started_at=now, finished_at=now, duration_ms=1, status=SchedulerRunStatus.FAILED, message="failed"))
        session.commit()
        assert system.scheduler_status(session).status == "failed"
