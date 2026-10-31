from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import InfrastructureAlert, InfrastructureEvent, InfrastructureSeverity
from app.monitoring import ComponentStatus, SystemStatus, inspect_system

_last_component_statuses: dict[str, str] = {}
_last_system_status: str | None = None


def _severity(status: str) -> InfrastructureSeverity:
    if status == "unavailable":
        return InfrastructureSeverity.CRITICAL
    if status == "degraded":
        return InfrastructureSeverity.WARNING
    return InfrastructureSeverity.INFO


def _record(session: Session, service: str, previous: str | None, current: str, description: str) -> InfrastructureEvent | None:
    if previous is None or previous == current:
        return None
    latest = session.scalar(
        select(InfrastructureEvent)
        .where(InfrastructureEvent.service == service)
        .order_by(InfrastructureEvent.occurred_at.desc())
        .limit(1)
    )
    if latest and latest.previous_status == previous and latest.new_status == current:
        return None
    event_type = "recovery" if current == "healthy" else "availability_change"
    event = InfrastructureEvent(service=service, event_type=event_type, previous_status=previous, new_status=current, description=description, severity=_severity(current))
    session.add(event)
    session.flush()
    if current != "healthy":
        session.add(InfrastructureAlert(event_id=event.id))
    elif previous != "healthy":
        for alert in session.scalars(select(InfrastructureAlert).join(InfrastructureEvent).where(InfrastructureEvent.service == service, InfrastructureAlert.is_resolved.is_(False))):
            alert.is_resolved = True
            alert.resolved_at = datetime.now(timezone.utc)
    return event


def record_transitions(session: Session, result: SystemStatus) -> list[InfrastructureEvent]:
    if any(component.name == "postgresql" and component.status != "healthy" for component in result.components):
        return []
    events = []
    for component in result.components:
        event = _record(session, component.name, component.previous_status, component.status, component.message)
        if event:
            events.append(event)
    event = _record(session, "system", result.previous_status, result.status, "System availability changed.")
    if event:
        events.append(event)
    session.commit()
    return events


def detect_transitions(result: SystemStatus) -> SystemStatus:
    global _last_system_status
    components = []
    for component in result.components:
        previous = _last_component_statuses.get(component.name)
        _last_component_statuses[component.name] = component.status
        components.append(component.model_copy(update={"previous_status": previous}))
    previous_system = _last_system_status
    _last_system_status = result.status
    return result.model_copy(update={"components": components, "previous_status": previous_system})


def run_infrastructure_check(session: Session) -> SystemStatus:
    """Probe, detect transitions, and persist them for an internal scheduler or endpoint."""
    result = detect_transitions(inspect_system())
    record_transitions(session, result)
    return result
