"""Conservatively remove only the approved synthetic DEMO dataset."""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db.models import Campaign, DistributionEvent, Experiment, Post, PublicMetricSnapshot, TrackingEvent, TrackingLink, campaign_posts
from app.db.session import get_engine

BATCH = "DEMO-ELHILO-2026-01"
CAMPAIGN_NAME = f"{BATCH} · Distribución informativa"


def validate_demo_target() -> None:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL must be set explicitly for the DEMO scripts.")
    parsed = urlsplit(value)
    database = unquote(parsed.path.lstrip("/"))
    if parsed.scheme not in {"postgresql+psycopg", "postgresql+psycopg2"} or database != "growth_lab_demo" or parsed.hostname not in {"localhost", "127.0.0.1", "postgres"} or parsed.port not in {5432, 5434}:
        raise SystemExit("Refusing to use a database other than the expected DEMO target.")


def load_plan(session: Session, batch: str) -> dict[str, object]:
    campaigns = list(session.scalars(select(Campaign).where(Campaign.name == CAMPAIGN_NAME)))
    if len(campaigns) != 1:
        raise ValueError("Expected exactly one approved DEMO campaign.")
    campaign = campaigns[0]
    experiments = list(session.scalars(select(Experiment).where(Experiment.campaign_id == campaign.id)))
    if len(experiments) != 1 or any(batch not in item.name or batch not in item.hypothesis for item in experiments):
        raise ValueError("DEMO experiment relationship is ambiguous.")
    post_ids = list(session.scalars(select(campaign_posts.c.post_id).where(campaign_posts.c.campaign_id == campaign.id)))
    if len(post_ids) != 1:
        raise ValueError("Expected exactly one DEMO post association.")
    post = session.get(Post, post_ids[0])
    linked_campaign_ids = list(session.scalars(select(campaign_posts.c.campaign_id).where(campaign_posts.c.post_id == post.id)))
    if post is None or batch not in (post.title or "") or linked_campaign_ids != [campaign.id]:
        raise ValueError("DEMO post is shared or cannot be proven to belong exclusively to this batch.")
    snapshots = list(session.scalars(select(PublicMetricSnapshot).where(PublicMetricSnapshot.post_id == post.id)))
    if len(snapshots) != 6 or any(batch not in (item.evidence_reference or "") for item in snapshots):
        raise ValueError("DEMO snapshots are ambiguous.")
    experiment = experiments[0]
    distribution = list(session.scalars(select(DistributionEvent).where(DistributionEvent.experiment_id == experiment.id)))
    if len(distribution) != 2 or any(batch not in (item.notes or "") for item in distribution):
        raise ValueError("DEMO distribution events are ambiguous.")
    links = list(session.scalars(select(TrackingLink).where(TrackingLink.experiment_id == experiment.id)))
    if len(links) != 1 or any(item.utm_content != batch or item.utm_campaign != "demo_el_hilo_2026_01" for item in links):
        raise ValueError("DEMO tracking links are ambiguous.")
    events = list(session.scalars(select(TrackingEvent).where(TrackingEvent.tracking_link_id.in_([item.id for item in links]))))
    if len(events) != 7 or any(item.event_type != "click" for item in events):
        raise ValueError("DEMO tracking events are ambiguous.")
    return {"campaign": campaign, "post": post, "experiment": experiment, "snapshots": snapshots, "distribution": distribution, "links": links, "events": events}


def summarize(plan: dict[str, object]) -> dict[str, int]:
    return {"campaigns": 1, "posts": 1, "experiments": 1, "distribution_events": len(plan["distribution"]), "tracking_links": len(plan["links"]), "tracking_events": len(plan["events"]), "public_metric_snapshots": len(plan["snapshots"])}


def delete_plan(session: Session, plan: dict[str, object]) -> None:
    session.execute(delete(TrackingEvent).where(TrackingEvent.id.in_([item.id for item in plan["events"]])))
    session.execute(delete(TrackingLink).where(TrackingLink.id.in_([item.id for item in plan["links"]])))
    session.execute(delete(DistributionEvent).where(DistributionEvent.id.in_([item.id for item in plan["distribution"]])))
    session.execute(delete(PublicMetricSnapshot).where(PublicMetricSnapshot.id.in_([item.id for item in plan["snapshots"]])))
    session.execute(delete(campaign_posts).where(campaign_posts.c.campaign_id == plan["campaign"].id))
    session.execute(delete(Experiment).where(Experiment.id == plan["experiment"].id))
    session.execute(delete(Campaign).where(Campaign.id == plan["campaign"].id))
    session.execute(delete(Post).where(Post.id == plan["post"].id))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--apply", action="store_true", help="Delete the approved DEMO dataset after confirmation.")
    args = parser.parse_args()
    if args.batch != BATCH:
        raise SystemExit(f"Only the approved DEMO batch {BATCH} is accepted.")
    validate_demo_target()
    with Session(get_engine()) as session:
        try:
            plan = load_plan(session, args.batch)
        except ValueError as error:
            raise SystemExit(f"No deletion performed: {error}") from error
        print({"batch": args.batch, "would_delete": summarize(plan)})
        if not args.apply:
            print("Dry run only. Pass --confirm and --apply to delete.")
            return
        if args.confirm != args.batch:
            raise SystemExit("No deletion performed: --confirm must exactly match --batch.")
        session.rollback()
        try:
            with session.begin():
                delete_plan(session, plan)
        except Exception as error:
            raise SystemExit(f"DEMO cleanup rolled back: {error}") from error
    print(f"Deleted approved DEMO batch {BATCH}: {summarize(plan)}")


if __name__ == "__main__":
    main()
