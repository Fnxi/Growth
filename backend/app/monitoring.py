import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_engine

logger = logging.getLogger("growth_lab.monitoring")
Status = Literal["healthy", "degraded", "unavailable"]


class ComponentStatus(BaseModel):
    name: str
    status: Status
    checked_at: datetime
    message: str
    previous_status: Status | None = None


class SystemStatus(BaseModel):
    status: Status
    checked_at: datetime
    components: list[ComponentStatus]
    previous_status: Status | None = None


def probe_postgres(engine: Engine | None = None) -> ComponentStatus:
    checked_at = datetime.now(timezone.utc)
    try:
        with (engine or get_engine()).connect() as connection:
            connection.execute(text("SELECT 1"))
        status: Status = "healthy"
        message = "PostgreSQL responded to a connectivity query."
        logger.info("postgres_connectivity_check status=healthy")
    except SQLAlchemyError:
        status = "unavailable"
        message = "PostgreSQL connectivity check failed."
        logger.warning("postgres_connectivity_check status=unavailable")
    return ComponentStatus(name="postgresql", status=status, checked_at=checked_at, message=message)


def check_postgres(engine: Engine | None = None) -> ComponentStatus:
    """Backward-compatible alias for the pure PostgreSQL probe."""
    return probe_postgres(engine)


def overall_status(components: list[ComponentStatus]) -> Status:
    statuses = {component.status for component in components}
    if statuses == {"healthy"}:
        return "healthy"
    if statuses == {"unavailable"}:
        return "unavailable"
    return "degraded"


def inspect_system() -> SystemStatus:
    checked_at = datetime.now(timezone.utc)
    api = ComponentStatus(name="fastapi", status="healthy", checked_at=checked_at, message="API status endpoint is responding.")
    database = probe_postgres()
    components = [api, database]
    status = overall_status(components)
    logger.info("system_check status=%s", status)
    return SystemStatus(status=status, checked_at=checked_at, components=components)


def check_system() -> SystemStatus:
    """Backward-compatible alias for the pure system inspection."""
    return inspect_system()
