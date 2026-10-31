from datetime import datetime, timedelta, timezone
from secrets import compare_digest
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import InfrastructureAlert, InfrastructureCheckRun, InfrastructureEvent, InfrastructureSchedulerHeartbeat, InfrastructureSeverity, SchedulerRunStatus
from app.monitor_scheduler import SCHEDULER_NAME
from app.db.session import get_db
from app.config import get_settings
from app.infrastructure_events import run_infrastructure_check
from app.monitoring import SystemStatus, inspect_system
from app.schemas import InfrastructureAlertRead, InfrastructureEventRead, SchedulerState, SchedulerStatusRead

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatus)
def system_status() -> SystemStatus:
    return inspect_system()


def require_system_check_token(x_system_check_token: str | None = Header(default=None)) -> None:
    expected = get_settings().system_check_token
    if not expected or not x_system_check_token or not compare_digest(expected, x_system_check_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="System check is not authorized.")


@router.post("/system/check", response_model=SystemStatus, dependencies=[Depends(require_system_check_token)])
def run_system_check(session: Session = Depends(get_db)) -> SystemStatus:
    return run_infrastructure_check(session)


@router.get("/system/scheduler", response_model=SchedulerStatusRead)
def scheduler_status(session: Session = Depends(get_db)) -> SchedulerStatusRead:
    settings = get_settings()
    last_check = session.scalar(select(InfrastructureCheckRun).order_by(InfrastructureCheckRun.started_at.desc()).limit(1))
    heartbeat = session.get(InfrastructureSchedulerHeartbeat, SCHEDULER_NAME)
    recent_errors = list(
        session.scalars(
            select(InfrastructureCheckRun)
            .where(InfrastructureCheckRun.status == SchedulerRunStatus.FAILED)
            .order_by(InfrastructureCheckRun.started_at.desc())
            .limit(5)
        )
    )
    now = datetime.now(timezone.utc)
    heartbeat_timeout = timedelta(seconds=max(settings.monitoring_check_interval_seconds * 3, 30))
    heartbeat_expires_at = heartbeat.last_heartbeat_at + heartbeat_timeout if heartbeat else None
    scheduler_state = SchedulerState.DISABLED
    if settings.monitoring_scheduler_enabled:
        if heartbeat is None:
            scheduler_state = SchedulerState.NOT_STARTED
        elif heartbeat.stopped_at and heartbeat.stopped_at >= heartbeat.last_heartbeat_at:
            scheduler_state = SchedulerState.STOPPED
        elif heartbeat_expires_at and heartbeat_expires_at < now:
            scheduler_state = SchedulerState.INACTIVE
        elif last_check and last_check.status == SchedulerRunStatus.FAILED:
            scheduler_state = SchedulerState.FAILED
        else:
            scheduler_state = SchedulerState.RUNNING
    next_execution_at = None
    if scheduler_state in {SchedulerState.RUNNING, SchedulerState.FAILED} and last_check and last_check.finished_at:
        next_execution_at = last_check.finished_at + timedelta(seconds=settings.monitoring_check_interval_seconds)
    return SchedulerStatusRead(
        enabled=settings.monitoring_scheduler_enabled,
        status=scheduler_state,
        interval_seconds=settings.monitoring_check_interval_seconds,
        last_check=last_check,
        next_execution_at=next_execution_at,
        last_heartbeat_at=heartbeat.last_heartbeat_at if heartbeat else None,
        heartbeat_expires_at=heartbeat_expires_at,
        recent_errors=recent_errors,
    )


@router.get("/system/events", response_model=list[InfrastructureEventRead])
def system_events(service: str | None = None, severity: InfrastructureSeverity | None = None, limit: int = 50, session: Session = Depends(get_db)) -> list[InfrastructureEvent]:
    query = select(InfrastructureEvent).order_by(InfrastructureEvent.occurred_at.desc()).limit(min(max(limit, 1), 200))
    if service:
        query = query.where(InfrastructureEvent.service == service)
    if severity:
        query = query.where(InfrastructureEvent.severity == severity)
    return list(session.scalars(query))


@router.get("/system/alerts", response_model=list[InfrastructureAlertRead])
def system_alerts(pending_only: bool = True, session: Session = Depends(get_db)) -> list[InfrastructureAlert]:
    query = select(InfrastructureAlert).options(selectinload(InfrastructureAlert.event)).order_by(InfrastructureAlert.created_at.desc())
    if pending_only:
        query = query.where(InfrastructureAlert.is_resolved.is_(False))
    return list(session.scalars(query))


@router.patch("/system/alerts/{alert_id}/acknowledge", response_model=InfrastructureAlertRead)
def acknowledge_alert(alert_id: UUID, session: Session = Depends(get_db)) -> InfrastructureAlert:
    alert = session.scalar(select(InfrastructureAlert).options(selectinload(InfrastructureAlert.event)).where(InfrastructureAlert.id == alert_id))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Infrastructure alert not found.")
    if not alert.is_acknowledged:
        alert.is_acknowledged = True
        alert.acknowledged_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(alert)
    return alert
