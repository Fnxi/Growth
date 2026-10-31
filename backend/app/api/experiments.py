from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.db.models import Campaign, Experiment, ExperimentStatus
from app.db.session import get_db
from app.schemas import ExperimentCreate, ExperimentRead, ExperimentStatusUpdate, ExperimentUpdate

router = APIRouter(prefix="/experiments", tags=["experiments"])


def get_experiment_or_404(experiment_id: UUID, session: Session) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found.")
    return experiment


@router.post("", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
def create_experiment(payload: ExperimentCreate, session: Session = Depends(get_db)) -> Experiment:
    if session.get(Campaign, payload.campaign_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown campaign_id.")
    experiment = Experiment(**payload.model_dump())
    session.add(experiment)
    commit_or_conflict(session.commit)
    session.refresh(experiment)
    return experiment


@router.get("", response_model=list[ExperimentRead])
def list_experiments(campaign_id: UUID | None = None, session: Session = Depends(get_db)) -> list[Experiment]:
    query = select(Experiment).order_by(Experiment.starts_at.desc())
    if campaign_id:
        query = query.where(Experiment.campaign_id == campaign_id)
    return list(session.scalars(query))


@router.get("/{experiment_id}", response_model=ExperimentRead)
def get_experiment(experiment_id: UUID, session: Session = Depends(get_db)) -> Experiment:
    return get_experiment_or_404(experiment_id, session)


@router.patch("/{experiment_id}", response_model=ExperimentRead)
def update_experiment(
    experiment_id: UUID, payload: ExperimentUpdate, session: Session = Depends(get_db)
) -> Experiment:
    experiment = get_experiment_or_404(experiment_id, session)
    data = payload.model_dump(exclude_unset=True)
    starts_at = data.get("starts_at", experiment.starts_at)
    ends_at = data.get("ends_at", experiment.ends_at)
    if starts_at and ends_at and ends_at < starts_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid experiment period.")
    for field, value in data.items():
        setattr(experiment, field, value)
    commit_or_conflict(session.commit)
    session.refresh(experiment)
    return experiment


@router.patch("/{experiment_id}/status", response_model=ExperimentRead)
def update_experiment_status(experiment_id: UUID, payload: ExperimentStatusUpdate, session: Session = Depends(get_db)) -> Experiment:
    experiment = get_experiment_or_404(experiment_id, session)
    allowed = {
        ExperimentStatus.DRAFT: {ExperimentStatus.PLANNED, ExperimentStatus.CANCELLED},
        ExperimentStatus.PLANNED: {ExperimentStatus.RUNNING, ExperimentStatus.CANCELLED},
        ExperimentStatus.RUNNING: {ExperimentStatus.COMPLETED, ExperimentStatus.CANCELLED},
        ExperimentStatus.COMPLETED: set(),
        ExperimentStatus.CANCELLED: set(),
    }
    if payload.status != experiment.status and payload.status not in allowed[experiment.status]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid experiment status transition.")
    if payload.status == ExperimentStatus.RUNNING and not all((experiment.objective, experiment.channel, experiment.success_criteria)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Objective, channel, and success criteria are required to start.")
    experiment.status = payload.status
    if payload.ended_at:
        if payload.ended_at < experiment.starts_at:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid experiment end date.")
        experiment.ends_at = payload.ended_at
    commit_or_conflict(session.commit)
    session.refresh(experiment)
    return experiment


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experiment(experiment_id: UUID, session: Session = Depends(get_db)) -> Response:
    session.delete(get_experiment_or_404(experiment_id, session))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
