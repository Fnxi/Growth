from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.api.posts import get_post_or_404
from app.db.models import MetricClassification, MetricDefinition, PublicMetricSnapshot
from app.db.session import get_db
from app.schemas import PublicMetricSnapshotCreate, PublicMetricSnapshotRead

router = APIRouter(tags=["public-metric-snapshots"])


@router.post("/metric-snapshots", response_model=PublicMetricSnapshotRead, status_code=201)
def create_snapshot(payload: PublicMetricSnapshotCreate, session: Session = Depends(get_db)) -> PublicMetricSnapshot:
    get_post_or_404(payload.post_id, session)
    definition = session.get(MetricDefinition, payload.metric_definition_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown metric_definition_id.")
    if definition.classification != MetricClassification.OBSERVED:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Snapshots require an observed metric definition.")
    snapshot = PublicMetricSnapshot(**payload.model_dump())
    session.add(snapshot)
    commit_or_conflict(session.commit)
    session.refresh(snapshot)
    return snapshot


@router.get("/posts/{post_id}/metric-snapshots", response_model=list[PublicMetricSnapshotRead])
def list_snapshots(post_id: UUID, metric_definition_id: UUID | None = None, captured_from: datetime | None = None, captured_to: datetime | None = None, session: Session = Depends(get_db)) -> list[PublicMetricSnapshot]:
    get_post_or_404(post_id, session)
    if captured_from and captured_to and captured_to < captured_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid capture period.")
    query = select(PublicMetricSnapshot).where(PublicMetricSnapshot.post_id == post_id)
    if metric_definition_id:
        query = query.where(PublicMetricSnapshot.metric_definition_id == metric_definition_id)
    if captured_from:
        query = query.where(PublicMetricSnapshot.captured_at >= captured_from)
    if captured_to:
        query = query.where(PublicMetricSnapshot.captured_at <= captured_to)
    return list(session.scalars(query.order_by(PublicMetricSnapshot.captured_at)))
