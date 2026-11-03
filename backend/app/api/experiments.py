from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.api.scoped_loaders import get_campaign_for_org, get_experiment_for_org
from app.db.models import Campaign, Experiment, ExperimentStatus
from app.db.session import get_db
from app.schemas import ExperimentCreate, ExperimentRead, ExperimentStatusUpdate, ExperimentUpdate

router = APIRouter(prefix="/organizations/{organization_id}/experiments", tags=["experiments"])
READ_ROLES = tuple(CommercialRole)
WRITE_ROLES = (CommercialRole.OWNER, CommercialRole.ADMIN, CommercialRole.EDITOR)
DELETE_ROLES = (CommercialRole.OWNER, CommercialRole.ADMIN)


@router.post("", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
def create_experiment(payload: ExperimentCreate, context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)), session: Session = Depends(get_db)) -> Experiment:
    get_campaign_for_org(session, context.organization.id, payload.campaign_id)
    experiment = Experiment(**payload.model_dump())
    session.add(experiment)
    commit_or_conflict(session.commit, session.rollback)
    session.refresh(experiment)
    return experiment


@router.get("", response_model=list[ExperimentRead])
def list_experiments(campaign_id: UUID | None = None, context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db)) -> list[Experiment]:
    query = select(Experiment).join(Campaign).where(Campaign.organization_id == context.organization.id).order_by(Experiment.starts_at.desc())
    if campaign_id:
        get_campaign_for_org(session, context.organization.id, campaign_id)
        query = query.where(Experiment.campaign_id == campaign_id)
    return list(session.scalars(query))


@router.get("/{experiment_id}", response_model=ExperimentRead)
def get_experiment(experiment_id: UUID, context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db)) -> Experiment:
    return get_experiment_for_org(session, context.organization.id, experiment_id)


@router.patch("/{experiment_id}", response_model=ExperimentRead)
def update_experiment(experiment_id: UUID, payload: ExperimentUpdate, context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)), session: Session = Depends(get_db)) -> Experiment:
    experiment = get_experiment_for_org(session, context.organization.id, experiment_id)
    data = payload.model_dump(exclude_unset=True)
    starts_at, ends_at = data.get("starts_at", experiment.starts_at), data.get("ends_at", experiment.ends_at)
    if starts_at and ends_at and ends_at < starts_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid experiment period.")
    for field, value in data.items():
        setattr(experiment, field, value)
    commit_or_conflict(session.commit, session.rollback)
    session.refresh(experiment)
    return experiment


@router.patch("/{experiment_id}/status", response_model=ExperimentRead)
def update_experiment_status(experiment_id: UUID, payload: ExperimentStatusUpdate, context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)), session: Session = Depends(get_db)) -> Experiment:
    experiment = get_experiment_for_org(session, context.organization.id, experiment_id)
    allowed = {ExperimentStatus.DRAFT: {ExperimentStatus.PLANNED, ExperimentStatus.CANCELLED}, ExperimentStatus.PLANNED: {ExperimentStatus.RUNNING, ExperimentStatus.CANCELLED}, ExperimentStatus.RUNNING: {ExperimentStatus.COMPLETED, ExperimentStatus.CANCELLED}, ExperimentStatus.COMPLETED: set(), ExperimentStatus.CANCELLED: set()}
    if payload.status != experiment.status and payload.status not in allowed[experiment.status]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid experiment status transition.")
    if payload.status == ExperimentStatus.RUNNING and not all((experiment.objective, experiment.channel, experiment.success_criteria)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Objective, channel, and success criteria are required to start.")
    experiment.status = payload.status
    if payload.ended_at:
        if payload.ended_at < experiment.starts_at:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid experiment end date.")
        experiment.ends_at = payload.ended_at
    commit_or_conflict(session.commit, session.rollback)
    session.refresh(experiment)
    return experiment


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experiment(experiment_id: UUID, context: OrgContext = Depends(require_org_roles(*DELETE_ROLES)), session: Session = Depends(get_db)) -> Response:
    session.delete(get_experiment_for_org(session, context.organization.id, experiment_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
