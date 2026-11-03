from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.scoped_loaders import (
    get_campaign_for_org,
    get_campaign_post_for_org,
    get_campaign_posts_for_org,
    get_distribution_event_for_org,
    get_experiment_for_org,
    get_post_for_org,
    get_snapshot_for_org,
    get_tracking_event_for_org,
    get_tracking_link_for_org,
)
from app.db.models import (
    Campaign,
    DistributionEvent,
    Experiment,
    MetricClassification,
    MetricDefinition,
    Organization,
    Post,
    PublicMetricSnapshot,
    TrackingEvent,
    TrackingLink,
    campaign_posts,
)


PROHIBITED_DATABASES = {"growth_lab", "growth_lab_demo"}


def isolated_database_url() -> str:
    database_url = os.environ.get("TENANCY_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TENANCY_TEST_DATABASE_URL is required for scoped loader integration tests.")
    parsed = urlsplit(database_url)
    database_name = parsed.path.lstrip("/")
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"} or not database_name:
        pytest.fail("TENANCY_TEST_DATABASE_URL must identify a PostgreSQL database.")
    if database_name in PROHIBITED_DATABASES:
        pytest.fail("Refusing to run scoped loader tests against a protected database.")
    if not (database_name.startswith("test_") or database_name.endswith("_test")):
        pytest.fail("TENANCY_TEST_DATABASE_URL must use a dedicated database named test_* or *_test.")
    return database_url


@pytest.fixture
def tenant_data() -> tuple[Session, dict[str, UUID]]:
    engine = create_engine(isolated_database_url())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    now = datetime.now(timezone.utc)
    try:
        organization_a = Organization(name="Scoped Organization A", slug_normalized=f"scoped-a-{uuid4().hex}")
        organization_b = Organization(name="Scoped Organization B", slug_normalized=f"scoped-b-{uuid4().hex}")
        session.add_all((organization_a, organization_b))
        session.flush()

        campaign_a = Campaign(name=f"Scoped Campaign A {uuid4().hex}", organization_id=organization_a.id)
        campaign_b = Campaign(name=f"Scoped Campaign B {uuid4().hex}", organization_id=organization_b.id)
        legacy_campaign = Campaign(name=f"Scoped Legacy Campaign {uuid4().hex}")
        post_a = Post(canonical_url=f"https://example.test/scoped/a/{uuid4()}", organization_id=organization_a.id)
        post_b = Post(canonical_url=f"https://example.test/scoped/b/{uuid4()}", organization_id=organization_b.id)
        legacy_post = Post(canonical_url=f"https://example.test/scoped/legacy/{uuid4()}")
        session.add_all((campaign_a, campaign_b, legacy_campaign, post_a, post_b, legacy_post))
        session.flush()
        session.execute(
            campaign_posts.insert(),
            (
                {"campaign_id": campaign_a.id, "post_id": post_a.id, "organization_id": organization_a.id},
                {"campaign_id": campaign_b.id, "post_id": post_b.id, "organization_id": organization_b.id},
                {"campaign_id": legacy_campaign.id, "post_id": legacy_post.id, "organization_id": None},
            ),
        )

        experiment_a = Experiment(
            campaign_id=campaign_a.id,
            name=f"Scoped Experiment A {uuid4().hex}",
            hypothesis="Scoped hypothesis",
            variable="channel",
            method="Scoped method",
            starts_at=now,
        )
        experiment_b = Experiment(
            campaign_id=campaign_b.id,
            name=f"Scoped Experiment B {uuid4().hex}",
            hypothesis="Scoped hypothesis",
            variable="channel",
            method="Scoped method",
            starts_at=now,
        )
        metric = MetricDefinition(
            name=f"scoped_metric_{uuid4().hex}",
            category="engagement",
            source="manual",
            limitations="Scoped loader test metric.",
            classification=MetricClassification.OBSERVED,
        )
        session.add_all((experiment_a, experiment_b, metric))
        session.flush()

        distribution_event_a = DistributionEvent(experiment_id=experiment_a.id, channel="newsletter", distributed_at=now)
        distribution_event_b = DistributionEvent(experiment_id=experiment_b.id, channel="newsletter", distributed_at=now)
        link_a = TrackingLink(
            experiment_id=experiment_a.id,
            code=f"scoped-a-{uuid4().hex}",
            destination_url="https://example.test/a",
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="scoped-a",
        )
        link_b = TrackingLink(
            experiment_id=experiment_b.id,
            code=f"scoped-b-{uuid4().hex}",
            destination_url="https://example.test/b",
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="scoped-b",
        )
        snapshot_a = PublicMetricSnapshot(
            post_id=post_a.id,
            metric_definition_id=metric.id,
            value=Decimal("1"),
            captured_at=now,
        )
        snapshot_b = PublicMetricSnapshot(
            post_id=post_b.id,
            metric_definition_id=metric.id,
            value=Decimal("2"),
            captured_at=now,
        )
        session.add_all((distribution_event_a, distribution_event_b, link_a, link_b, snapshot_a, snapshot_b))
        session.flush()
        tracking_event_a = TrackingEvent(tracking_link_id=link_a.id, event_type="click")
        tracking_event_b = TrackingEvent(tracking_link_id=link_b.id, event_type="click")
        session.add_all((tracking_event_a, tracking_event_b))
        session.flush()

        yield session, {
            "organization_a": organization_a.id,
            "organization_b": organization_b.id,
            "campaign_a": campaign_a.id,
            "campaign_b": campaign_b.id,
            "legacy_campaign": legacy_campaign.id,
            "post_a": post_a.id,
            "post_b": post_b.id,
            "legacy_post": legacy_post.id,
            "experiment_a": experiment_a.id,
            "experiment_b": experiment_b.id,
            "distribution_event_a": distribution_event_a.id,
            "distribution_event_b": distribution_event_b.id,
            "tracking_link_a": link_a.id,
            "tracking_link_b": link_b.id,
            "tracking_event_a": tracking_event_a.id,
            "tracking_event_b": tracking_event_b.id,
            "snapshot_a": snapshot_a.id,
            "snapshot_b": snapshot_b.id,
        }
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def assert_not_found(loader, tenant_data: dict[str, UUID], resource_key: str) -> None:
    with pytest.raises(HTTPException) as error:
        loader(tenant_data["organization_a"], tenant_data[resource_key])
    assert error.value.status_code == status.HTTP_404_NOT_FOUND


def test_scoped_loaders_return_every_resource_owned_by_the_requested_organization(
    tenant_data: tuple[Session, dict[str, UUID]]
) -> None:
    session, data = tenant_data
    organization_id = data["organization_a"]
    assert get_campaign_for_org(session, organization_id, data["campaign_a"]).id == data["campaign_a"]
    assert get_post_for_org(session, organization_id, data["post_a"]).id == data["post_a"]
    assert get_experiment_for_org(session, organization_id, data["experiment_a"]).id == data["experiment_a"]
    assert get_distribution_event_for_org(session, organization_id, data["distribution_event_a"]).id == data["distribution_event_a"]
    assert get_tracking_link_for_org(session, organization_id, data["tracking_link_a"]).id == data["tracking_link_a"]
    assert get_tracking_event_for_org(session, organization_id, data["tracking_event_a"]).id == data["tracking_event_a"]
    assert get_snapshot_for_org(session, organization_id, data["snapshot_a"]).id == data["snapshot_a"]


@pytest.mark.parametrize(
    ("loader_name", "resource_key"),
    (
        ("campaign", "campaign_b"),
        ("post", "post_b"),
        ("experiment", "experiment_b"),
        ("distribution_event", "distribution_event_b"),
        ("tracking_link", "tracking_link_b"),
        ("tracking_event", "tracking_event_b"),
        ("snapshot", "snapshot_b"),
    ),
)
def test_scoped_loaders_hide_another_organizations_resources(
    tenant_data: tuple[Session, dict[str, UUID]], loader_name: str, resource_key: str
) -> None:
    loaders = {
        "campaign": get_campaign_for_org,
        "post": get_post_for_org,
        "experiment": get_experiment_for_org,
        "distribution_event": get_distribution_event_for_org,
        "tracking_link": get_tracking_link_for_org,
        "tracking_event": get_tracking_event_for_org,
        "snapshot": get_snapshot_for_org,
    }
    session, data = tenant_data
    assert_not_found(lambda organization_id, resource_id: loaders[loader_name](session, organization_id, resource_id), data, resource_key)


def test_scoped_loaders_hide_missing_and_historical_null_scoped_resources(
    tenant_data: tuple[Session, dict[str, UUID]]
) -> None:
    session, data = tenant_data
    organization_id = data["organization_a"]
    with pytest.raises(HTTPException) as missing:
        get_campaign_for_org(session, organization_id, uuid4())
    assert missing.value.status_code == status.HTTP_404_NOT_FOUND
    for loader, resource_key in (
        (get_campaign_for_org, "legacy_campaign"),
        (get_post_for_org, "legacy_post"),
    ):
        with pytest.raises(HTTPException) as historical:
            loader(session, organization_id, data[resource_key])
        assert historical.value.status_code == status.HTTP_404_NOT_FOUND
    with pytest.raises(HTTPException) as association:
        get_campaign_post_for_org(session, organization_id, data["legacy_campaign"], data["legacy_post"])
    assert association.value.status_code == status.HTTP_404_NOT_FOUND


def test_campaign_post_helpers_require_the_bridge_and_both_root_scopes(
    tenant_data: tuple[Session, dict[str, UUID]]
) -> None:
    session, data = tenant_data
    organization_id = data["organization_a"]
    assert get_campaign_post_for_org(session, organization_id, data["campaign_a"], data["post_a"]).id == data["post_a"]
    assert [post.id for post in get_campaign_posts_for_org(session, organization_id, data["campaign_a"])] == [data["post_a"]]
    with pytest.raises(HTTPException) as cross_tenant:
        get_campaign_post_for_org(session, organization_id, data["campaign_b"], data["post_b"])
    assert cross_tenant.value.status_code == status.HTTP_404_NOT_FOUND
