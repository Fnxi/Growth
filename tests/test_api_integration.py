from collections.abc import Generator
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_session_factory
from app.db.models import InfrastructureEvent
from app.config import get_settings
import app.infrastructure_events as infrastructure_events
from app.main import app

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") and not Path(".env").exists(),
    reason="Integration tests require DATABASE_URL or a local .env file.",
)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    statement = text(
        "TRUNCATE TABLE tracking_events, tracking_links, distribution_events, "
        "public_metric_snapshots, experiments, campaign_posts, campaigns, "
        "posts RESTART IDENTITY CASCADE"
    )
    with get_session_factory()() as session:
        session.execute(statement)
        session.commit()
    yield
    with get_session_factory()() as session:
        session.execute(statement)
        session.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def test_post_campaign_and_experiment_crud(client: TestClient) -> None:
    post_response = client.post(
        "/posts",
        json={
            "canonical_url": "https://www.instagram.com/p/example-post/",
            "title": "Encuesta publica",
        },
    )
    assert post_response.status_code == 201
    post_id = post_response.json()["id"]

    campaign_response = client.post(
        "/campaigns",
        json={
            "name": "Distribucion neutral",
            "post_ids": [post_id],
            "starts_at": "2026-10-30T12:00:00Z",
        },
    )
    assert campaign_response.status_code == 201
    campaign = campaign_response.json()
    assert [post["id"] for post in campaign["posts"]] == [post_id]

    experiment_response = client.post(
        "/experiments",
        json={
            "campaign_id": campaign["id"],
            "name": "Canal informativo",
            "hypothesis": "Un enlace informativo permite medir clics propios.",
            "variable": "canal de distribucion",
            "method": "Registro temporal de enlaces UTM.",
            "starts_at": "2026-10-30T12:00:00Z",
        },
    )
    assert experiment_response.status_code == 201
    experiment_id = experiment_response.json()["id"]

    update_response = client.patch(
        f"/experiments/{experiment_id}",
        json={"result": "Sin resultado aun.", "conclusion": "Pendiente de medicion."},
    )
    assert update_response.status_code == 200
    assert update_response.json()["conclusion"] == "Pendiente de medicion."

    list_response = client.get(f"/experiments?campaign_id={campaign['id']}")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [experiment_id]

    assert client.delete(f"/experiments/{experiment_id}").status_code == 204
    assert client.delete(f"/campaigns/{campaign['id']}").status_code == 204
    assert client.delete(f"/posts/{post_id}").status_code == 204


def test_inconsistent_relationships_and_periods_are_rejected(client: TestClient) -> None:
    missing_post = "00000000-0000-0000-0000-000000000001"
    campaign_response = client.post(
        "/campaigns", json={"name": "Invalida", "post_ids": [missing_post]}
    )
    assert campaign_response.status_code == 422

    campaign_response = client.post("/campaigns", json={"name": "Valida"})
    campaign_id = campaign_response.json()["id"]
    experiment_response = client.post(
        "/experiments",
        json={
            "campaign_id": campaign_id,
            "name": "Periodo invalido",
            "hypothesis": "Hipotesis valida.",
            "variable": "canal",
            "method": "Metodo valido.",
            "starts_at": "2026-10-31T12:00:00Z",
            "ends_at": "2026-10-30T12:00:00Z",
        },
    )
    assert experiment_response.status_code == 422


def test_snapshots_are_scoped_to_posts_and_chronological(client: TestClient) -> None:
    definitions = client.get("/metric-definitions").json()
    likes = next(item for item in definitions if item["name"] == "visible_likes")
    calculated = next(item for item in definitions if item["name"] == "first_party_visits")
    first_post = client.post("/posts", json={"canonical_url": "https://instagram.com/p/first/"}).json()
    second_post = client.post("/posts", json={"canonical_url": "https://instagram.com/p/second/"}).json()
    for value, captured_at in [("10", "2026-01-01T10:00:00Z"), ("15", "2026-01-02T10:00:00Z")]:
        response = client.post("/metric-snapshots", json={"post_id": first_post["id"], "metric_definition_id": likes["id"], "value": value, "captured_at": captured_at, "evidence_reference": "manual-note-1"})
        assert response.status_code == 201
    assert client.post("/metric-snapshots", json={"post_id": second_post["id"], "metric_definition_id": likes["id"], "value": "99", "captured_at": "2026-01-01T10:00:00Z"}).status_code == 201
    assert client.post("/metric-snapshots", json={"post_id": first_post["id"], "metric_definition_id": calculated["id"], "value": "1", "captured_at": "2026-01-03T10:00:00Z"}).status_code == 422
    history = client.get(f"/posts/{first_post['id']}/metric-snapshots?captured_from=2026-01-02T00:00:00Z").json()
    assert [item["value"] for item in history] == ["15.0000"]
    assert client.get("/posts/00000000-0000-0000-0000-000000000001/metric-snapshots").status_code == 404


def test_distribution_events_filter_by_channel_and_period(client: TestClient) -> None:
    campaign = client.post("/campaigns", json={"name": "Canales"}).json()
    experiment = client.post("/experiments", json={"campaign_id": campaign["id"], "name": "Comparacion", "hypothesis": "Hipotesis.", "variable": "canal", "method": "Registro.", "starts_at": "2026-01-01T00:00:00Z"}).json()
    for channel, distributed_at in [("newsletter", "2026-01-01T10:00:00Z"), ("social", "2026-01-02T10:00:00Z")]:
        assert client.post("/distribution-events", json={"experiment_id": experiment["id"], "channel": channel, "distributed_at": distributed_at, "notes": "Registro verificable."}).status_code == 201
    events = client.get(f"/experiments/{experiment['id']}/distribution-events?channel=social&distributed_from=2026-01-02T00:00:00Z").json()
    assert [item["channel"] for item in events] == ["social"]
    assert client.get("/experiments/00000000-0000-0000-0000-000000000001/distribution-events").status_code == 404


def test_dashboard_summary_and_empty_metric_series(client: TestClient) -> None:
    summary = client.get("/dashboard/summary")
    assert summary.status_code == 200
    assert summary.json()["campaigns"] == 0
    series = client.get("/analytics/observed-metrics?metric_name=visible_likes")
    assert series.status_code == 200
    assert series.json()["points"] == []
    system = client.get("/system/status")
    assert system.status_code == 200
    assert system.json()["status"] == "healthy"
    assert {item["name"] for item in system.json()["components"]} == {"fastapi", "postgresql"}


def test_experiment_lifecycle_and_empty_evaluation(client: TestClient) -> None:
    campaign = client.post("/campaigns", json={"name": "Lifecycle"}).json()
    experiment = client.post("/experiments", json={"campaign_id": campaign["id"], "name": "Lifecycle test", "hypothesis": "Validation.", "objective": "Measure controlled actions.", "variable": "channel", "channel": "newsletter", "method": "Manual distribution log.", "evaluation_metrics": ["visible_likes"], "success_criteria": "Record two observations.", "starts_at": "2026-01-01T00:00:00Z"}).json()
    assert experiment["status"] == "draft"
    assert client.patch(f"/experiments/{experiment['id']}/status", json={"status": "planned"}).status_code == 200
    assert client.patch(f"/experiments/{experiment['id']}/status", json={"status": "running"}).json()["status"] == "running"
    evaluation = client.get(f"/experiments/{experiment['id']}/evaluation").json()
    assert evaluation["metrics"] == []
    assert "may be shared" in evaluation["limitations"][0]
    assert client.patch(f"/experiments/{experiment['id']}/status", json={"status": "completed", "ended_at": "2026-01-02T00:00:00Z"}).json()["status"] == "completed"
    assert client.patch(f"/experiments/{experiment['id']}/status", json={"status": "running"}).status_code == 422


def test_system_status_is_read_only_and_internal_check_persists_transition(client: TestClient) -> None:
    with get_session_factory()() as session:
        before = len(session.query(InfrastructureEvent).all())
    assert client.get("/system/status").status_code == 200
    with get_session_factory()() as session:
        assert len(session.query(InfrastructureEvent).all()) == before
    assert client.post("/system/check").status_code == 403
    infrastructure_events._last_component_statuses.clear()
    infrastructure_events._last_component_statuses["postgresql"] = "unavailable"
    infrastructure_events._last_system_status = "degraded"
    token = get_settings().system_check_token
    response = client.post("/system/check", headers={"X-System-Check-Token": token})
    assert response.status_code == 200
    with get_session_factory()() as session:
        assert len(session.query(InfrastructureEvent).all()) > before
