from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.api.experiments import get_experiment_or_404
from app.db.models import DistributionEvent
from app.db.session import get_db
from app.schemas import DistributionEventCreate, DistributionEventRead

router = APIRouter(tags=["distribution-events"])


@router.post("/distribution-events", response_model=DistributionEventRead, status_code=201)
def create_distribution_event(payload: DistributionEventCreate, session: Session = Depends(get_db)) -> DistributionEvent:
    get_experiment_or_404(payload.experiment_id, session)
    event = DistributionEvent(**payload.model_dump())
    session.add(event)
    commit_or_conflict(session.commit)
    session.refresh(event)
    return event


@router.get("/experiments/{experiment_id}/distribution-events", response_model=list[DistributionEventRead])
def list_distribution_events(experiment_id: UUID, channel: str | None = None, distributed_from: datetime | None = None, distributed_to: datetime | None = None, session: Session = Depends(get_db)) -> list[DistributionEvent]:
    get_experiment_or_404(experiment_id, session)
    if distributed_from and distributed_to and distributed_to < distributed_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid distribution period.")
    query = select(DistributionEvent).where(DistributionEvent.experiment_id == experiment_id)
    if channel:
        query = query.where(DistributionEvent.channel == channel)
    if distributed_from:
        query = query.where(DistributionEvent.distributed_at >= distributed_from)
    if distributed_to:
        query = query.where(DistributionEvent.distributed_at <= distributed_to)
    return list(session.scalars(query.order_by(DistributionEvent.distributed_at)))
