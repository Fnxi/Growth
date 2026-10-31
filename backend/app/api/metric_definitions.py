from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.db.models import MetricClassification, MetricDefinition
from app.db.session import get_db
from app.schemas import MetricDefinitionCreate, MetricDefinitionRead, MetricDefinitionUpdate

router = APIRouter(prefix="/metric-definitions", tags=["metric-definitions"])


def get_metric_definition_or_404(metric_definition_id: UUID, session: Session) -> MetricDefinition:
    definition = session.get(MetricDefinition, metric_definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Metric definition not found.")
    return definition


@router.post("", response_model=MetricDefinitionRead, status_code=201)
def create_metric_definition(payload: MetricDefinitionCreate, session: Session = Depends(get_db)) -> MetricDefinition:
    definition = MetricDefinition(**payload.model_dump())
    session.add(definition)
    commit_or_conflict(session.commit)
    session.refresh(definition)
    return definition


@router.get("", response_model=list[MetricDefinitionRead])
def list_metric_definitions(classification: MetricClassification | None = None, session: Session = Depends(get_db)) -> list[MetricDefinition]:
    query = select(MetricDefinition).order_by(MetricDefinition.name)
    if classification is not None:
        query = query.where(MetricDefinition.classification == classification)
    return list(session.scalars(query))


@router.patch("/{metric_definition_id}", response_model=MetricDefinitionRead)
def update_metric_definition(metric_definition_id: UUID, payload: MetricDefinitionUpdate, session: Session = Depends(get_db)) -> MetricDefinition:
    definition = get_metric_definition_or_404(metric_definition_id, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(definition, field, value)
    commit_or_conflict(session.commit)
    session.refresh(definition)
    return definition


@router.delete("/{metric_definition_id}", status_code=204)
def delete_metric_definition(metric_definition_id: UUID, session: Session = Depends(get_db)) -> Response:
    session.delete(get_metric_definition_or_404(metric_definition_id, session))
    commit_or_conflict(session.commit)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
