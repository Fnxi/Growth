from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_session_factory
from app.main import app
from app.api.tracking import _requests, request_allowed


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    with get_session_factory()() as session:
        session.execute(text("TRUNCATE TABLE tracking_events, tracking_links, distribution_events, public_metric_snapshots, experiments, campaign_posts, campaigns, posts RESTART IDENTITY CASCADE"))
        session.commit()
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def make_experiment(client: TestClient) -> dict:
    campaign = client.post("/campaigns", json={"name": "Tracking"}).json()
    return client.post("/experiments", json={"campaign_id": campaign["id"], "name": "Enlace", "hypothesis": "Hipotesis.", "variable": "enlace", "method": "Registro.", "starts_at": "2026-01-01T00:00:00Z"}).json()


def test_tracking_redirect_records_click_and_can_be_disabled(client: TestClient) -> None:
    experiment = make_experiment(client)
    response = client.post("/tracking-links", json={"experiment_id": experiment["id"], "destination_url": "https://www.instagram.com/p/example/", "utm_source": "newsletter", "utm_medium": "email", "utm_campaign": "neutral"})
    assert response.status_code == 201
    link = response.json()
    assert len(link["code"]) >= 16
    redirect = client.get(f"/r/{link['code']}", follow_redirects=False, headers={"referer": "https://example.org/article"})
    assert redirect.status_code == 307
    assert "utm_source=newsletter" in redirect.headers["location"]
    assert client.get(f"/tracking-links/{link['id']}/clicks").json()["clicks_registered"] == 1
    assert client.patch(f"/tracking-links/{link['id']}", json={"is_active": False}).status_code == 200
    assert client.get(f"/r/{link['code']}", follow_redirects=False).status_code == 404


def test_tracking_rejects_unsafe_destinations_and_groups_clicks(client: TestClient) -> None:
    experiment = make_experiment(client)
    rejected = client.post("/tracking-links", json={"experiment_id": experiment["id"], "destination_url": "https://evil.example/path", "utm_source": "x", "utm_medium": "x", "utm_campaign": "x"})
    assert rejected.status_code == 422
    assert client.get("/r/not-real", follow_redirects=False).status_code == 404
    link = client.post("/tracking-links", json={"experiment_id": experiment["id"], "destination_url": "https://instagram.com/p/example/", "utm_source": "social", "utm_medium": "organic", "utm_campaign": "neutral"}).json()
    assert client.get(f"/r/{link['code']}", follow_redirects=False).status_code == 307
    summary = client.get("/tracking/attribution?group_by=utm_source").json()
    assert summary["results"] == [{"dimension": "social", "clicks_registered": 1}]


def test_tracking_preserves_query_and_fragment_and_rejects_ports(client: TestClient) -> None:
    experiment = make_experiment(client)
    link = client.post("/tracking-links", json={"experiment_id": experiment["id"], "destination_url": "https://instagram.com/p/example/?existing=a%20b&existing=two#section", "utm_source": "social media", "utm_medium": "organic", "utm_campaign": "neutral"}).json()
    redirect = client.get(f"/r/{link['code']}", follow_redirects=False)
    location = redirect.headers["location"]
    assert "existing=a+b&existing=two" in location
    assert "utm_source=social+media" in location
    assert location.endswith("#section")
    for destination in ("http://instagram.com/p/example/", "https://instagram.com:444/p/example/"):
        response = client.post("/tracking-links", json={"experiment_id": experiment["id"], "destination_url": destination, "utm_source": "x", "utm_medium": "x", "utm_campaign": "x"})
        assert response.status_code == 422


def test_rate_limiter_rejects_excessive_requests() -> None:
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/r/code", "headers": [], "client": ("abuse-test", 1234)})
    _requests.clear()
    assert all(request_allowed(request) for _ in range(30))
    assert not request_allowed(request)
    _requests.clear()
