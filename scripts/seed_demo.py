"""Create the reproducible, synthetic commercial demo dataset."""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import get_settings
from app.db.models import Campaign, Experiment, ExperimentStatus, MetricClassification, MetricDefinition, Organization, OrganizationStatus, Post, PublicMetricSnapshot, TrackingEvent, TrackingLink, DistributionEvent, campaign_posts
from app.operational_intelligence.service import OperationalIntelligenceService

BATCH = "DEMO-ELHILO-2026-01"
POST_URL = "https://example.com/growth-hacking-lab/demo-el-hilo-mx-2026-01"
CAMPAIGN_NAME = f"{BATCH} · Distribución informativa"


def demo_database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL must be set explicitly for the DEMO scripts.")
    parsed = urlsplit(value)
    database = unquote(parsed.path.lstrip("/"))
    if parsed.scheme not in {"postgresql+psycopg", "postgresql+psycopg2"} or database != "growth_lab_demo" or parsed.hostname not in {"localhost", "127.0.0.1", "postgres"} or parsed.port not in {5432, 5434}:
        raise SystemExit("Refusing to use a database other than the expected DEMO target.")
    return value


def parse_anchor(value: str) -> datetime:
    anchor = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if anchor.tzinfo is None:
        raise argparse.ArgumentTypeError("--anchor-at must include a UTC offset.")
    return anchor.astimezone(timezone.utc)


def validate_arguments(args: argparse.Namespace) -> None:
    if args.batch != BATCH:
        raise SystemExit(f"Only the approved DEMO batch {BATCH} is accepted.")


def plan(anchor: datetime) -> dict[str, object]:
    return {
        "batch": BATCH,
        "anchor_at": anchor.isoformat(),
        "records": {
            "posts": 1,
            "campaigns": 1,
            "experiments": 1,
            "distribution_events": 2,
            "tracking_links": 1,
            "tracking_events": 7,
            "public_metric_snapshots": 6,
        },
        "notice": "All commercial values are synthetic DEMO data, not Instagram results.",
    }


def resolve_organization(session: Session, organization_id: UUID) -> Organization:
    organization = session.scalar(select(Organization).where(Organization.id == organization_id, Organization.status == OrganizationStatus.ACTIVE, Organization.deleted_at.is_(None)))
    if organization is None:
        raise ValueError("The requested DEMO organization does not exist or is not active.")
    return organization


def create_dataset(session: Session, anchor: datetime, organization_id: UUID) -> None:
    if session.scalar(select(Campaign.id).where(Campaign.name == CAMPAIGN_NAME, Campaign.organization_id == organization_id)) is not None:
        raise ValueError("The approved DEMO batch already exists.")
    if session.scalar(select(Post.id).where(Post.canonical_url == POST_URL, Post.organization_id == organization_id)) is not None:
        raise ValueError("The DEMO post URL already exists.")

    definitions = {item.name: item for item in session.scalars(select(MetricDefinition).where(MetricDefinition.name.in_(["visible_likes", "visible_comments"]))) }
    if set(definitions) != {"visible_likes", "visible_comments"} or any(item.classification != MetricClassification.OBSERVED for item in definitions.values()):
        raise ValueError("Required observed metric definitions are unavailable.")

    post = Post(canonical_url=POST_URL, platform="demo_synthetic", title=f"{BATCH} · Publicación ficticia", published_at=anchor - timedelta(days=3), organization_id=organization_id)
    campaign = Campaign(name=CAMPAIGN_NAME, description=f"{BATCH}. Datos sintéticos para demostración; no representan resultados reales.", starts_at=anchor - timedelta(days=3), ends_at=anchor, organization_id=organization_id)
    session.add_all((post, campaign))
    session.flush()
    session.execute(campaign_posts.insert().values(campaign_id=campaign.id, post_id=post.id, organization_id=organization_id))

    experiment = Experiment(campaign_id=campaign.id, name=f"{BATCH} · Variante de distribución", objective="Demostrar el flujo de medición con datos sintéticos.", hypothesis=f"{BATCH}: dos acciones de distribución pueden documentarse junto con clics propios y observaciones públicas simuladas.", variable="Canal de distribución DEMO", method="Registro temporal sintético y comparación first/last; no infiere causalidad.", channel="demo_synthetic", success_criteria="Mostrar trazabilidad de acciones, clics propios y variación de observaciones DEMO.", evaluation_metrics=["visible_likes", "visible_comments", "first_party_link_clicks"], starts_at=anchor - timedelta(days=2), ends_at=anchor, result="DEMO: variaciones sintéticas disponibles para visualización.", conclusion="DEMO: los datos ilustran el flujo, no crecimiento real.", status=ExperimentStatus.COMPLETED)
    session.add(experiment)
    session.flush()

    session.add_all([
        DistributionEvent(experiment_id=experiment.id, channel="newsletter_demo", distributed_at=anchor - timedelta(days=2, hours=-2), notes=f"{BATCH}. Acción sintética de demostración."),
        DistributionEvent(experiment_id=experiment.id, channel="community_demo", distributed_at=anchor - timedelta(days=1, hours=-3), notes=f"{BATCH}. Acción sintética de demostración."),
    ])
    link = TrackingLink(experiment_id=experiment.id, code="demo-elhilo-2026-01", destination_url="https://example.com/", utm_source="demo_newsletter", utm_medium="demo", utm_campaign="demo_el_hilo_2026_01", utm_content=BATCH, is_active=True)
    session.add(link)
    session.flush()
    session.add_all([TrackingEvent(tracking_link_id=link.id, occurred_at=anchor - timedelta(hours=18 - index), event_type="click", referrer_domain="demo.local") for index in range(7)])

    snapshots = []
    for offset, likes, comments in ((2, "100", "8"), (1, "120", "10"), (0, "168", "15")):
        captured_at = anchor - timedelta(days=offset)
        evidence = f"{BATCH}: observación sintética para demostración; no es una métrica real de Instagram."
        snapshots.extend([
            PublicMetricSnapshot(post_id=post.id, metric_definition_id=definitions["visible_likes"].id, value=Decimal(likes), captured_at=captured_at, evidence_reference=evidence),
            PublicMetricSnapshot(post_id=post.id, metric_definition_id=definitions["visible_comments"].id, value=Decimal(comments), captured_at=captured_at, evidence_reference=evidence),
        ])
    session.add_all(snapshots)
    session.flush()

    summary = OperationalIntelligenceService(get_settings()).summary(session, organization_id)
    changes = [item for item in summary["anomalies"] if item.category == "metric_change"]
    if len(changes) != 2 or not summary["recommendations"]:
        raise ValueError("DEMO analytics validation did not produce the approved metric-change findings.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--anchor-at", type=parse_anchor, required=True)
    parser.add_argument("--organization-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true", help="Write the approved DEMO dataset.")
    args = parser.parse_args()
    validate_arguments(args)
    target = demo_database_url()
    print(plan(args.anchor_at))
    if not args.apply:
        print("Dry run only. Pass --apply to write the DEMO dataset.")
        return
    engine = create_engine(target, pool_pre_ping=True)
    with Session(engine) as session:
        resolve_organization(session, args.organization_id)
        try:
            with session.begin():
                create_dataset(session, args.anchor_at, args.organization_id)
        except Exception as error:
            raise SystemExit(f"DEMO seed rolled back: {error}") from error
    print(f"Created approved DEMO batch {BATCH}.")


if __name__ == "__main__":
    main()
