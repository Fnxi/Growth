from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.common import commit_or_conflict
from app.db.models import Campaign, Post
from app.db.session import get_db
from app.schemas import CampaignCreate, CampaignRead, CampaignUpdate

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def get_campaign_or_404(campaign_id: UUID, session: Session) -> Campaign:
    campaign = session.scalar(
        select(Campaign).options(selectinload(Campaign.posts)).where(Campaign.id == campaign_id)
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")
    return campaign


def resolve_posts(post_ids: list[UUID], session: Session) -> list[Post]:
    posts = list(session.scalars(select(Post).where(Post.id.in_(post_ids)))) if post_ids else []
    if len(posts) != len(set(post_ids)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown post_id.")
    return posts


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, session: Session = Depends(get_db)) -> Campaign:
    data = payload.model_dump(exclude={"post_ids"})
    campaign = Campaign(**data, posts=resolve_posts(payload.post_ids, session))
    session.add(campaign)
    commit_or_conflict(session.commit)
    return get_campaign_or_404(campaign.id, session)


@router.get("", response_model=list[CampaignRead])
def list_campaigns(session: Session = Depends(get_db)) -> list[Campaign]:
    return list(session.scalars(select(Campaign).options(selectinload(Campaign.posts)).order_by(Campaign.created_at.desc())))


@router.get("/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: UUID, session: Session = Depends(get_db)) -> Campaign:
    return get_campaign_or_404(campaign_id, session)


@router.patch("/{campaign_id}", response_model=CampaignRead)
def update_campaign(campaign_id: UUID, payload: CampaignUpdate, session: Session = Depends(get_db)) -> Campaign:
    campaign = get_campaign_or_404(campaign_id, session)
    data = payload.model_dump(exclude_unset=True, exclude={"post_ids"})
    starts_at = data.get("starts_at", campaign.starts_at)
    ends_at = data.get("ends_at", campaign.ends_at)
    if starts_at and ends_at and ends_at < starts_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid campaign period.")
    for field, value in data.items():
        setattr(campaign, field, value)
    if "post_ids" in payload.model_fields_set:
        campaign.posts = resolve_posts(payload.post_ids or [], session)
    commit_or_conflict(session.commit)
    return get_campaign_or_404(campaign.id, session)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: UUID, session: Session = Depends(get_db)) -> Response:
    session.delete(get_campaign_or_404(campaign_id, session))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
