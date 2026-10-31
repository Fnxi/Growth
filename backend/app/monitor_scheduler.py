"""Independent, PostgreSQL-coordinated infrastructure check scheduler."""

import logging
import signal
import time
from collections.abc import Callable
from datetime import datetime, timezone
from threading import Event

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import InfrastructureCheckRun, InfrastructureSchedulerHeartbeat, SchedulerRunStatus
from app.db.session import get_session_factory
from app.infrastructure_events import run_infrastructure_check

logger = logging.getLogger(__name__)

# Advisory locks are scoped to a PostgreSQL connection and shared by every scheduler instance.
SCHEDULER_LOCK_ID = 7_403_001
SCHEDULER_NAME = "infrastructure"


class InfrastructureScheduler:
    def __init__(self, session_factory: sessionmaker[Session] | None = None, interval_seconds: int | None = None) -> None:
        settings = get_settings()
        self.session_factory = session_factory or get_session_factory()
        self.interval_seconds = interval_seconds or settings.monitoring_check_interval_seconds

    def run_once(self) -> bool:
        """Run one check when no other scheduler currently owns the database lock."""
        try:
            # A dedicated connection keeps the session-level advisory lock alive while
            # run_infrastructure_check commits its own persisted transitions.
            with self.session_factory() as bootstrap_session:
                engine = bootstrap_session.get_bind()
            with engine.connect() as connection:
                with Session(bind=connection, autoflush=False, expire_on_commit=False) as session:
                    self._record_heartbeat(session)
                    acquired = bool(connection.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": SCHEDULER_LOCK_ID}).scalar())
                    # End the lock acquisition transaction without releasing the
                    # session-level lock, so the bound session can commit normally.
                    connection.commit()
                    if not acquired:
                        logger.info("Infrastructure check skipped because another scheduler holds the lock.")
                        return False
                    try:
                        return self._run_locked(session)
                    finally:
                        connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": SCHEDULER_LOCK_ID})
        except SQLAlchemyError:
            logger.exception("Infrastructure scheduler could not connect to PostgreSQL.")
            return False

    @staticmethod
    def _record_heartbeat(session: Session) -> None:
        heartbeat = session.get(InfrastructureSchedulerHeartbeat, SCHEDULER_NAME)
        now = datetime.now(timezone.utc)
        if heartbeat is None:
            session.add(InfrastructureSchedulerHeartbeat(scheduler_name=SCHEDULER_NAME, last_heartbeat_at=now))
        else:
            heartbeat.last_heartbeat_at = now
            heartbeat.stopped_at = None
        session.commit()

    def mark_stopped(self) -> None:
        """Persist a clean shutdown when PostgreSQL remains available."""
        try:
            with self.session_factory() as session:
                heartbeat = session.get(InfrastructureSchedulerHeartbeat, SCHEDULER_NAME)
                if heartbeat:
                    heartbeat.stopped_at = datetime.now(timezone.utc)
                    session.commit()
        except SQLAlchemyError:
            logger.exception("Infrastructure scheduler shutdown could not be persisted.")

    def _run_locked(self, session: Session) -> bool:
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run = InfrastructureCheckRun(
            started_at=started_at,
            status=SchedulerRunStatus.RUNNING,
            message="Infrastructure check started.",
        )
        session.add(run)
        session.commit()
        logger.info("Infrastructure check started.")

        try:
            result = run_infrastructure_check(session)
            run.status = SchedulerRunStatus.SUCCESS if result.status == "healthy" else SchedulerRunStatus.DEGRADED
            run.message = f"Infrastructure check completed with system status: {result.status}."
            succeeded = True
        except Exception:
            session.rollback()
            session.add(run)
            run.status = SchedulerRunStatus.FAILED
            run.message = "Infrastructure check failed; see scheduler logs for details."
            succeeded = False
            logger.exception("Infrastructure check failed.")

        run.finished_at = datetime.now(timezone.utc)
        run.duration_ms = round((time.monotonic() - started) * 1000)
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Infrastructure check result could not be persisted.")
            return False
        logger.info("Infrastructure check finished with status=%s duration_ms=%s.", run.status.value, run.duration_ms)
        return succeeded

    def run_forever(self, sleep: Callable[[float], None] = time.sleep, stop_event: Event | None = None) -> None:
        logger.info("Infrastructure scheduler started with interval_seconds=%s.", self.interval_seconds)
        while not stop_event or not stop_event.is_set():
            self.run_once()
            if stop_event:
                stop_event.wait(self.interval_seconds)
            else:
                sleep(self.interval_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.monitoring_scheduler_enabled:
        logger.info("Infrastructure scheduler is disabled by MONITORING_SCHEDULER_ENABLED.")
        return
    scheduler = InfrastructureScheduler()
    stop_event = Event()

    def request_stop(_signal_number: int, _frame: object) -> None:
        logger.info("Infrastructure scheduler received a shutdown signal.")
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        scheduler.run_forever(stop_event=stop_event)
    finally:
        scheduler.mark_stopped()


if __name__ == "__main__":
    main()
