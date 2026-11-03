from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Campaign,
    DistributionEvent,
    Experiment,
    Post,
    PublicMetricSnapshot,
    TrackingEvent,
    TrackingLink,
    campaign_posts,
)


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found.")


def get_campaign_for_org(session: Session, organization_id: UUID, campaign_id: UUID) -> Campaign:
    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == organization_id)
    )
    if campaign is None:
        raise _not_found("Campaign")
    return campaign


def get_post_for_org(session: Session, organization_id: UUID, post_id: UUID) -> Post:
    post = session.scalar(select(Post).where(Post.id == post_id, Post.organization_id == organization_id))
    if post is None:
        raise _not_found("Post")
    return post


def get_experiment_for_org(session: Session, organization_id: UUID, experiment_id: UUID) -> Experiment:
    experiment = session.scalar(
        select(Experiment)
        .join(Campaign, Experiment.campaign_id == Campaign.id)
        .where(Experiment.id == experiment_id, Campaign.organization_id == organization_id)
    )
    if experiment is None:
        raise _not_found("Experiment")
    return experiment


def get_distribution_event_for_org(
    session: Session, organization_id: UUID, distribution_event_id: UUID
) -> DistributionEvent:
    event = session.scalar(
        select(DistributionEvent)
        .join(Experiment, DistributionEvent.experiment_id == Experiment.id)
        .join(Campaign, Experiment.campaign_id == Campaign.id)
        .where(DistributionEvent.id == distribution_event_id, Campaign.organization_id == organization_id)
    )
    if event is None:
        raise _not_found("Distribution event")
    return event


def get_tracking_link_for_org(session: Session, organization_id: UUID, tracking_link_id: UUID) -> TrackingLink:
    link = session.scalar(
        select(TrackingLink)
        .join(Experiment, TrackingLink.experiment_id == Experiment.id)
        .join(Campaign, Experiment.campaign_id == Campaign.id)
        .where(TrackingLink.id == tracking_link_id, Campaign.organization_id == organization_id)
    )
    if link is None:
        raise _not_found("Tracking link")
    return link


def get_tracking_event_for_org(session: Session, organization_id: UUID, tracking_event_id: UUID) -> TrackingEvent:
    event = session.scalar(
        select(TrackingEvent)
        .join(TrackingLink, TrackingEvent.tracking_link_id == TrackingLink.id)
        .join(Experiment, TrackingLink.experiment_id == Experiment.id)
        .join(Campaign, Experiment.campaign_id == Campaign.id)
        .where(TrackingEvent.id == tracking_event_id, Campaign.organization_id == organization_id)
    )
    if event is None:
        raise _not_found("Tracking event")
    return event


def get_snapshot_for_org(session: Session, organization_id: UUID, snapshot_id: UUID) -> PublicMetricSnapshot:
    snapshot = session.scalar(
        select(PublicMetricSnapshot)
        .join(Post, PublicMetricSnapshot.post_id == Post.id)
        .where(PublicMetricSnapshot.id == snapshot_id, Post.organization_id == organization_id)
    )
    if snapshot is None:
        raise _not_found("Public metric snapshot")
    return snapshot


def get_campaign_post_for_org(session: Session, organization_id: UUID, campaign_id: UUID, post_id: UUID) -> Post:
    """Return a post only when its bridge row and both commercial roots share the organization."""
    post = session.scalar(
        select(Post)
        .join(campaign_posts, campaign_posts.c.post_id == Post.id)
        .join(Campaign, campaign_posts.c.campaign_id == Campaign.id)
        .where(
            campaign_posts.c.campaign_id == campaign_id,
            campaign_posts.c.post_id == post_id,
            campaign_posts.c.organization_id == organization_id,
            Campaign.organization_id == organization_id,
            Post.organization_id == organization_id,
        )
    )
    if post is None:
        raise _not_found("Campaign post association")
    return post


def get_campaign_posts_for_org(session: Session, organization_id: UUID, campaign_id: UUID) -> list[Post]:
    """Return only bridge rows whose scope agrees with both the campaign and each post."""
    get_campaign_for_org(session, organization_id, campaign_id)
    return list(
        session.scalars(
            select(Post)
            .join(campaign_posts, campaign_posts.c.post_id == Post.id)
            .join(Campaign, campaign_posts.c.campaign_id == Campaign.id)
            .where(
                campaign_posts.c.campaign_id == campaign_id,
                campaign_posts.c.organization_id == organization_id,
                Campaign.organization_id == organization_id,
                Post.organization_id == organization_id,
            )
        )
    )
