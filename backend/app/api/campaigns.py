from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, flush_or_conflict
from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.api.scoped_loaders import get_campaign_for_org, get_campaign_posts_for_org, get_post_for_org
from app.db.models import Campaign, Post, campaign_posts
from app.db.session import get_db
from app.schemas import CampaignCreate, CampaignRead, CampaignUpdate, PostRead

router = APIRouter(prefix="/organizations/{organization_id}/campaigns", tags=["campaigns"])

READ_ROLES = tuple(CommercialRole)
WRITE_ROLES = (CommercialRole.OWNER, CommercialRole.ADMIN, CommercialRole.EDITOR)
DELETE_ROLES = (CommercialRole.OWNER, CommercialRole.ADMIN)


def serialize_campaign(campaign: Campaign, posts: list[Post]) -> CampaignRead:
    return CampaignRead(
        id=campaign.id,
        name=campaign.name,
        description=campaign.description,
        starts_at=campaign.starts_at,
        ends_at=campaign.ends_at,
        posts=[PostRead.model_validate(post) for post in posts],
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


def resolve_posts_for_org(post_ids: list[UUID], session: Session, organization_id: UUID) -> list[Post]:
    if len(post_ids) != len(set(post_ids)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Duplicate post_id.")
    return [get_post_for_org(session, organization_id, post_id) for post_id in post_ids]


def replace_campaign_posts(campaign: Campaign, posts: list[Post], session: Session, organization_id: UUID) -> None:
    session.execute(
        delete(campaign_posts).where(
            campaign_posts.c.campaign_id == campaign.id,
            campaign_posts.c.organization_id == organization_id,
        )
    )
    if posts:
        session.execute(
            campaign_posts.insert(),
            [
                {"campaign_id": campaign.id, "post_id": post.id, "organization_id": organization_id}
                for post in posts
            ],
        )


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignCreate,
    context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)),
    session: Session = Depends(get_db),
) -> CampaignRead:
    organization_id = context.organization.id
    posts = resolve_posts_for_org(payload.post_ids, session, organization_id)
    campaign = Campaign(**payload.model_dump(exclude={"post_ids"}), organization_id=organization_id)
    session.add(campaign)
    flush_or_conflict(session.flush, session.rollback)
    replace_campaign_posts(campaign, posts, session, organization_id)
    commit_or_conflict(session.commit, session.rollback)
    return serialize_campaign(campaign, get_campaign_posts_for_org(session, organization_id, campaign.id))


@router.get("", response_model=list[CampaignRead])
def list_campaigns(
    context: OrgContext = Depends(require_org_roles(*READ_ROLES)),
    session: Session = Depends(get_db),
) -> list[CampaignRead]:
    organization_id = context.organization.id
    campaigns = session.scalars(
        select(Campaign)
        .where(Campaign.organization_id == organization_id)
        .order_by(Campaign.created_at.desc())
    )
    return [
        serialize_campaign(campaign, get_campaign_posts_for_org(session, organization_id, campaign.id))
        for campaign in campaigns
    ]


@router.get("/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: UUID,
    context: OrgContext = Depends(require_org_roles(*READ_ROLES)),
    session: Session = Depends(get_db),
) -> CampaignRead:
    organization_id = context.organization.id
    campaign = get_campaign_for_org(session, organization_id, campaign_id)
    return serialize_campaign(campaign, get_campaign_posts_for_org(session, organization_id, campaign.id))


@router.patch("/{campaign_id}", response_model=CampaignRead)
def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)),
    session: Session = Depends(get_db),
) -> CampaignRead:
    organization_id = context.organization.id
    campaign = get_campaign_for_org(session, organization_id, campaign_id)
    data = payload.model_dump(exclude_unset=True, exclude={"post_ids"})
    starts_at = data.get("starts_at", campaign.starts_at)
    ends_at = data.get("ends_at", campaign.ends_at)
    if starts_at and ends_at and ends_at < starts_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid campaign period.")
    for field, value in data.items():
        setattr(campaign, field, value)
    if "post_ids" in payload.model_fields_set:
        replace_campaign_posts(
            campaign,
            resolve_posts_for_org(payload.post_ids or [], session, organization_id),
            session,
            organization_id,
        )
    commit_or_conflict(session.commit, session.rollback)
    return serialize_campaign(campaign, get_campaign_posts_for_org(session, organization_id, campaign.id))


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: UUID,
    context: OrgContext = Depends(require_org_roles(*DELETE_ROLES)),
    session: Session = Depends(get_db),
) -> Response:
    session.delete(get_campaign_for_org(session, context.organization.id, campaign_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
