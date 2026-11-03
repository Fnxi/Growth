from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.api.scoped_loaders import get_post_for_org
from app.db.models import MetricClassification, MetricDefinition, PublicMetricSnapshot
from app.db.session import get_db
from app.schemas import PublicMetricSnapshotCreate, PublicMetricSnapshotRead

router = APIRouter(prefix="/organizations/{organization_id}", tags=["public-metric-snapshots"])
READ_ROLES = tuple(CommercialRole)
WRITE_ROLES = (CommercialRole.OWNER, CommercialRole.ADMIN, CommercialRole.EDITOR)


@router.post("/metric-snapshots", response_model=PublicMetricSnapshotRead, status_code=201)
def create_snapshot(payload: PublicMetricSnapshotCreate, context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)), session: Session = Depends(get_db)) -> PublicMetricSnapshot:
    get_post_for_org(session, context.organization.id, payload.post_id)
    definition = session.get(MetricDefinition, payload.metric_definition_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown metric_definition_id.")
    if definition.classification != MetricClassification.OBSERVED:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Snapshots require an observed metric definition.")
    snapshot = PublicMetricSnapshot(**payload.model_dump())
    session.add(snapshot)
    commit_or_conflict(session.commit, session.rollback)
    session.refresh(snapshot)
    return snapshot


@router.get("/posts/{post_id}/metric-snapshots", response_model=list[PublicMetricSnapshotRead])
def list_snapshots(post_id: UUID, metric_definition_id: UUID | None = None, captured_from: datetime | None = None, captured_to: datetime | None = None, context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db)) -> list[PublicMetricSnapshot]:
    get_post_for_org(session, context.organization.id, post_id)
    if captured_from and captured_to and captured_to < captured_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid capture period.")
    query = select(PublicMetricSnapshot).where(PublicMetricSnapshot.post_id == post_id)
    if metric_definition_id: query = query.where(PublicMetricSnapshot.metric_definition_id == metric_definition_id)
    if captured_from: query = query.where(PublicMetricSnapshot.captured_at >= captured_from)
    if captured_to: query = query.where(PublicMetricSnapshot.captured_at <= captured_to)
    return list(session.scalars(query.order_by(PublicMetricSnapshot.captured_at)))
