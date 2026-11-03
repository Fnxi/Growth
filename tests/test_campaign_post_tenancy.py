from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api import assistant as assistant_api
from app.assistant.providers import ProviderResult
from app.assistant.service import AssistantService
from app.config import Settings, get_settings
from app.db.models import (
    AuthSession,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    MetricClassification,
    MetricDefinition,
    User,
    campaign_posts,
)
from app.db.session import get_db
from app.main import create_app
from app.security.crypto import sign_access_token


PROHIBITED_DATABASES = {"growth_lab", "growth_lab_demo"}


def isolated_database_url() -> str:
    database_url = os.environ.get("TENANCY_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TENANCY_TEST_DATABASE_URL is required for Campaign/Post tenancy integration tests.")
    parsed = urlsplit(database_url)
    database_name = parsed.path.lstrip("/")
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"} or not database_name:
        pytest.fail("TENANCY_TEST_DATABASE_URL must identify a PostgreSQL database.")
    if database_name in PROHIBITED_DATABASES:
        pytest.fail("Refusing to run Campaign/Post tenancy tests against a protected database.")
    if not (database_name.startswith("test_") or database_name.endswith("_test")):
        pytest.fail("TENANCY_TEST_DATABASE_URL must use a dedicated database named test_* or *_test.")
    return database_url


def build_settings(database_url: str) -> Settings:
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("=")
    return Settings(
        database_url=database_url,
        app_env="development",
        security_jwt_active_kid="test",
        security_jwt_keyring=json.dumps({"test": key}),
        security_cors_allowed_origins="http://localhost:8501",
    )


def add_principal(
    session: Session,
    email: str,
    memberships: list[tuple[Organization, OrganizationRole]],
) -> tuple[User, AuthSession]:
    user = User(email_display=email, email_normalized=email, password_hash="unused")
    session.add(user)
    session.flush()
    auth_session = AuthSession(user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    session.add(auth_session)
    session.add_all(
        OrganizationMembership(
            user_id=user.id,
            organization_id=organization.id,
            role=role,
            status=MembershipStatus.ACTIVE,
        )
        for organization, role in memberships
    )
    session.flush()
    return user, auth_session


@pytest.fixture
def tenancy_client() -> tuple[TestClient, dict[str, object]]:
    database_url = isolated_database_url()
    engine = create_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    settings = build_settings(database_url)
    try:
        organization_a = Organization(name="Campaign Tenant A", slug_normalized=f"campaign-tenant-a-{uuid4().hex}")
        organization_b = Organization(name="Campaign Tenant B", slug_normalized=f"campaign-tenant-b-{uuid4().hex}")
        session.add_all((organization_a, organization_b))
        session.flush()

        owner, owner_session = add_principal(
            session,
            f"owner-{uuid4().hex}@example.test",
            [(organization_a, OrganizationRole.OWNER), (organization_b, OrganizationRole.OWNER)],
        )
        reader, reader_session = add_principal(
            session,
            f"reader-{uuid4().hex}@example.test",
            [(organization_a, OrganizationRole.VIEWER)],
        )
        editor, editor_session = add_principal(
            session,
            f"editor-{uuid4().hex}@example.test",
            [(organization_a, OrganizationRole.ANALYST)],
        )
        admin, admin_session = add_principal(
            session,
            f"admin-{uuid4().hex}@example.test",
            [(organization_a, OrganizationRole.ADMIN)],
        )
        outsider, outsider_session = add_principal(session, f"outsider-{uuid4().hex}@example.test", [])

        app = create_app(settings)

        def test_db():
            yield session

        app.dependency_overrides[get_db] = test_db
        app.dependency_overrides[get_settings] = lambda: settings
        headers = {
            "owner": {"Authorization": f"Bearer {sign_access_token(str(owner.id), settings, owner_session.id)}"},
            "reader": {"Authorization": f"Bearer {sign_access_token(str(reader.id), settings, reader_session.id)}"},
            "editor": {"Authorization": f"Bearer {sign_access_token(str(editor.id), settings, editor_session.id)}"},
            "admin": {"Authorization": f"Bearer {sign_access_token(str(admin.id), settings, admin_session.id)}"},
            "outsider": {"Authorization": f"Bearer {sign_access_token(str(outsider.id), settings, outsider_session.id)}"},
        }
        with TestClient(app) as client:
            yield client, {"organization_a": organization_a.id, "organization_b": organization_b.id, "headers": headers, "session": session}
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def organization_url(data: dict[str, object], organization_key: str, resource: str) -> str:
    return f"/organizations/{data[organization_key]}/{resource}"


def test_assistant_requires_tenant_membership_and_never_shares_context(
    tenancy_client: tuple[TestClient, dict[str, object]]
) -> None:
    class CapturingProvider:
        def __init__(self) -> None:
            self.inputs: list[str] = []

        def respond(self, _instructions: str, input_text: str, _max_output_tokens: int) -> ProviderResult:
            self.inputs.append(input_text)
            return ProviderResult(
                content='{"answer":"Observed.","observed_facts":[],"interpretations":[],"recommendations":[],"insufficient_information":[],"references":[]}',
                input_tokens=1,
                output_tokens=1,
            )

    client, data = tenancy_client
    headers = data["headers"]
    assert isinstance(headers, dict)
    campaigns_a = organization_url(data, "organization_a", "campaigns")
    campaigns_b = organization_url(data, "organization_b", "campaigns")
    assistant_a = organization_url(data, "organization_a", "assistant")
    assistant_b = organization_url(data, "organization_b", "assistant")
    campaign_a_name = f"tenant-a-private-{uuid4().hex}"
    campaign_b_name = f"tenant-b-private-{uuid4().hex}"
    assert client.post(campaigns_a, headers=headers["owner"], json={"name": campaign_a_name}).status_code == 201
    assert client.post(campaigns_b, headers=headers["owner"], json={"name": campaign_b_name}).status_code == 201

    provider = CapturingProvider()
    app = client.app
    app.dependency_overrides[assistant_api.get_assistant_service] = lambda: AssistantService(
        SimpleNamespace(
            ai_enabled=True,
            ai_provider="openai",
            ai_openai_api_key="test-key",
            ai_model="test-model",
            ai_timeout_seconds=1,
            ai_max_output_tokens=200,
            ai_max_context_characters=1000,
        ),
        provider,
    )
    try:
        assert client.get("/assistant/status").status_code == 404
        assert client.post("/assistant/chat", json={"question": "experimento"}).status_code == 404
        assert client.get(f"{assistant_a}/status").status_code == 401
        assert client.get(f"{assistant_a}/status", headers=headers["outsider"]).status_code == 403
        assert client.get(f"{assistant_a}/status", headers=headers["reader"]).status_code == 200
        assert client.post(f"{assistant_a}/chat", headers=headers["reader"], json={"question": "experimento"}).status_code == 200
        assert client.post(f"{assistant_a}/diagnosis", headers=headers["reader"]).status_code == 200
        assert client.post(
            f"{assistant_a}/chat",
            headers=headers["reader"],
            json={"question": "experimento", "organization_id": str(data["organization_b"])},
        ).status_code == 200
        assert client.post(f"{assistant_b}/chat", headers=headers["owner"], json={"question": "experimento"}).status_code == 200
    finally:
        app.dependency_overrides.pop(assistant_api.get_assistant_service, None)

    assert len(provider.inputs) == 4
    chat_a, diagnosis_a, claimed_tenant_b_from_a, chat_b = provider.inputs
    for payload in (chat_a, diagnosis_a, claimed_tenant_b_from_a, chat_b):
        assert "InfrastructureEvent" not in payload
        assert "InfrastructureAlert" not in payload
        assert "InfrastructureCheckRun" not in payload
        assert "operational_intelligence" not in payload
    assert campaign_a_name in chat_a
    assert campaign_b_name not in chat_a
    assert campaign_b_name not in diagnosis_a
    assert campaign_a_name in claimed_tenant_b_from_a
    assert campaign_b_name not in claimed_tenant_b_from_a
    assert campaign_b_name in chat_b
    assert campaign_a_name not in chat_b


def test_campaign_and_post_routes_enforce_tenant_scope_roles_and_explicit_associations(
    tenancy_client: tuple[TestClient, dict[str, object]]
) -> None:
    client, data = tenancy_client
    headers = data["headers"]
    assert isinstance(headers, dict)
    posts_a = organization_url(data, "organization_a", "posts")
    posts_b = organization_url(data, "organization_b", "posts")
    campaigns_a = organization_url(data, "organization_a", "campaigns")
    campaigns_b = organization_url(data, "organization_b", "campaigns")

    assert client.get(posts_a).status_code == 401
    assert client.get(posts_a, headers=headers["outsider"]).status_code == 403

    post_a = client.post(
        posts_a,
        headers=headers["owner"],
        json={"canonical_url": f"https://example.test/a/{uuid4()}", "title": "Tenant A"},
    )
    assert post_a.status_code == 201
    post_a_id = post_a.json()["id"]
    post_b = client.post(
        posts_b,
        headers=headers["owner"],
        json={"canonical_url": f"https://example.test/b/{uuid4()}", "title": "Tenant B"},
    )
    assert post_b.status_code == 201
    post_b_id = post_b.json()["id"]

    campaign = client.post(
        campaigns_a,
        headers=headers["owner"],
        json={"name": f"Tenant A Campaign {uuid4().hex}", "post_ids": [post_a_id]},
    )
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]
    assert [post["id"] for post in campaign.json()["posts"]] == [post_a_id]
    session = data["session"]
    assert isinstance(session, Session)
    association = session.execute(
        select(campaign_posts).where(
            campaign_posts.c.campaign_id == campaign_id,
            campaign_posts.c.post_id == post_a_id,
        )
    ).mappings().one()
    assert association["campaign_id"] == UUID(campaign_id)
    assert association["post_id"] == UUID(post_a_id)
    assert association["organization_id"] == data["organization_a"]
    assert client.post(
        campaigns_a,
        headers=headers["owner"],
        json={"name": campaign.json()["name"]},
    ).status_code == 409
    assert client.post(
        campaigns_a,
        headers=headers["owner"],
        json={"name": f"Recovered Campaign {uuid4().hex}"},
    ).status_code == 201

    assert client.post(
        campaigns_a,
        headers=headers["owner"],
        json={"name": f"Cross Tenant Campaign {uuid4().hex}", "post_ids": [post_b_id]},
    ).status_code == 404
    campaign_b = client.post(
        campaigns_b,
        headers=headers["owner"],
        json={"name": f"Tenant B Campaign {uuid4().hex}", "description": "Tenant B data", "post_ids": [post_b_id]},
    )
    assert campaign_b.status_code == 201
    campaign_b_id = campaign_b.json()["id"]
    assert client.get(f"{campaigns_a}/{campaign_b_id}", headers=headers["owner"]).status_code == 404
    assert client.patch(f"{campaigns_a}/{campaign_b_id}", headers=headers["owner"], json={"description": "Changed"}).status_code == 404
    assert client.delete(f"{campaigns_a}/{campaign_b_id}", headers=headers["owner"]).status_code == 404
    tenant_b_campaign = client.get(f"{campaigns_b}/{campaign_b_id}", headers=headers["owner"])
    assert tenant_b_campaign.status_code == 200
    assert tenant_b_campaign.json()["description"] == "Tenant B data"
    assert client.get(f"{posts_a}/{post_b_id}", headers=headers["owner"]).status_code == 404
    assert client.get(f"{campaigns_a}/{campaign_id}", headers=headers["reader"]).status_code == 200
    assert client.post(posts_a, headers=headers["reader"], json={"canonical_url": f"https://example.test/reader/{uuid4()}"}).status_code == 403
    assert client.delete(f"{posts_a}/{post_a_id}", headers=headers["reader"]).status_code == 403

    assert client.patch(f"{posts_a}/{post_a_id}", headers=headers["editor"], json={"title": "Editor update"}).status_code == 200
    assert client.delete(f"{posts_a}/{post_a_id}", headers=headers["editor"]).status_code == 403
    assert client.patch(
        f"{posts_a}/{post_a_id}",
        headers=headers["owner"],
        json={"organization_id": str(data["organization_b"])},
    ).status_code == 422
    assert client.patch(
        f"{campaigns_a}/{campaign_id}",
        headers=headers["owner"],
        json={"organization_id": str(data["organization_b"])},
    ).status_code == 422
    assert client.patch(
        f"{campaigns_a}/{campaign_id}",
        headers=headers["owner"],
        json={"post_ids": [post_a_id]},
    ).status_code == 200
    experiment_a = client.post(
        organization_url(data, "organization_a", "experiments"),
        headers=headers["owner"],
        json={"campaign_id": campaign_id, "name": f"Experiment A {uuid4().hex}", "hypothesis": "h", "variable": "v", "method": "m", "starts_at": "2026-01-01T00:00:00Z"},
    )
    assert experiment_a.status_code == 201
    experiment_a_id = experiment_a.json()["id"]
    assert client.post(
        organization_url(data, "organization_a", "experiments"),
        headers=headers["owner"],
        json={"campaign_id": campaign_b_id, "name": f"Cross experiment {uuid4().hex}", "hypothesis": "h", "variable": "v", "method": "m", "starts_at": "2026-01-01T00:00:00Z"},
    ).status_code == 404
    experiment_b = client.post(
        organization_url(data, "organization_b", "experiments"),
        headers=headers["owner"],
        json={"campaign_id": campaign_b_id, "name": f"Experiment B {uuid4().hex}", "hypothesis": "h", "variable": "v", "method": "m", "starts_at": "2026-01-01T00:00:00Z"},
    )
    assert experiment_b.status_code == 201
    experiment_b_id = experiment_b.json()["id"]
    experiments_a = organization_url(data, "organization_a", "experiments")
    assert client.get(f"{experiments_a}/{experiment_b_id}", headers=headers["owner"]).status_code == 404
    assert client.patch(f"{experiments_a}/{experiment_b_id}", headers=headers["owner"], json={"result": "x"}).status_code == 404
    assert client.delete(f"{experiments_a}/{experiment_b_id}", headers=headers["owner"]).status_code == 404
    assert client.get(f"{organization_url(data, 'organization_b', 'experiments')}/{experiment_b_id}", headers=headers["owner"]).status_code == 200
    assert client.post(
        organization_url(data, "organization_a", "distribution-events"),
        headers=headers["editor"],
        json={"experiment_id": experiment_a_id, "channel": "newsletter", "distributed_at": "2026-01-01T01:00:00Z"},
    ).status_code == 201
    assert client.get(f"{experiments_a}/{experiment_a_id}/distribution-events", headers=headers["reader"]).status_code == 200
    distribution_b = client.post(
        organization_url(data, "organization_b", "distribution-events"),
        headers=headers["owner"],
        json={"experiment_id": experiment_b_id, "channel": "tenant-b", "distributed_at": "2026-01-01T01:00:00Z"},
    )
    assert distribution_b.status_code == 201
    assert client.get(f"{experiments_a}/{experiment_b_id}/distribution-events", headers=headers["owner"]).status_code == 404
    assert client.get(
        f"{organization_url(data, 'organization_b', 'experiments')}/{experiment_b_id}/distribution-events",
        headers=headers["owner"],
    ).json()[0]["id"] == distribution_b.json()["id"]
    link = client.post(
        organization_url(data, "organization_a", "tracking-links"),
        headers=headers["owner"],
        json={"experiment_id": experiment_a_id, "destination_url": "https://www.instagram.com/p/example/", "utm_source": "newsletter", "utm_medium": "email", "utm_campaign": "tenant-a"},
    )
    assert link.status_code == 201
    public_redirect = client.get(f"/r/{link.json()['code']}", follow_redirects=False)
    assert public_redirect.status_code == 307
    assert public_redirect.content == b""
    public_text = " ".join(public_redirect.headers.values())
    for identifier in (str(data["organization_a"]), campaign_id, experiment_a_id, link.json()["id"]):
        assert identifier not in public_text
    assert client.get(f"{organization_url(data, 'organization_a', 'tracking-links')}/{link.json()['id']}/clicks", headers=headers["reader"]).json()["clicks_registered"] == 1
    link_b = client.post(
        organization_url(data, "organization_b", "tracking-links"),
        headers=headers["owner"],
        json={"experiment_id": experiment_b_id, "destination_url": "https://www.instagram.com/p/example-b/", "utm_source": "tenant-b", "utm_medium": "email", "utm_campaign": "tenant-b"},
    )
    assert link_b.status_code == 201
    assert client.get(f"/r/{link_b.json()['code']}", follow_redirects=False).status_code == 307
    tracking_links_a = organization_url(data, "organization_a", "tracking-links")
    assert client.get(f"{tracking_links_a}?experiment_id={experiment_b_id}", headers=headers["owner"]).status_code == 404
    assert client.patch(f"{tracking_links_a}/{link_b.json()['id']}", headers=headers["owner"], json={"is_active": False}).status_code == 404
    assert client.get(
        f"{organization_url(data, 'organization_b', 'tracking-links')}?experiment_id={experiment_b_id}",
        headers=headers["owner"],
    ).json()[0]["is_active"] is True
    attribution_a = client.get(
        f"{organization_url(data, 'organization_a', 'tracking/attribution')}?group_by=utm_source",
        headers=headers["reader"],
    )
    assert attribution_a.status_code == 200
    assert attribution_a.json()["results"] == [{"dimension": "newsletter", "clicks_registered": 1}]
    metric = MetricDefinition(name=f"tenant_metric_{uuid4().hex}", category="engagement", source="manual", limitations="test", classification=MetricClassification.OBSERVED)
    session.add(metric)
    session.commit()
    assert client.post(
        organization_url(data, "organization_a", "metric-snapshots"),
        headers=headers["editor"],
        json={"post_id": post_a_id, "metric_definition_id": str(metric.id), "value": "1", "captured_at": "2026-01-01T02:00:00Z"},
    ).status_code == 201
    assert client.post(
        organization_url(data, "organization_a", "metric-snapshots"),
        headers=headers["editor"],
        json={"post_id": post_b_id, "metric_definition_id": str(metric.id), "value": "1", "captured_at": "2026-01-01T02:00:00Z"},
    ).status_code == 404
    snapshot_b = client.post(
        organization_url(data, "organization_b", "metric-snapshots"),
        headers=headers["owner"],
        json={"post_id": post_b_id, "metric_definition_id": str(metric.id), "value": "9", "captured_at": "2026-01-01T02:00:00Z"},
    )
    assert snapshot_b.status_code == 201
    evaluation_a = client.get(f"{experiments_a}/{experiment_a_id}/evaluation", headers=headers["reader"])
    assert evaluation_a.status_code == 200
    assert {metric["post_id"] for metric in evaluation_a.json()["metrics"]} == {post_a_id}
    assert client.get(f"{experiments_a}/{experiment_b_id}/evaluation", headers=headers["owner"]).status_code == 404
    assert client.get(campaigns_a, headers=headers["owner"]).json()[0]["id"] == campaign_id
    assert client.get("/posts", headers=headers["owner"]).status_code == 404
    assert client.get("/campaigns", headers=headers["owner"]).status_code == 404

    delete_target = client.post(
        posts_a,
        headers=headers["owner"],
        json={"canonical_url": f"https://example.test/delete/{uuid4()}"},
    )
    assert delete_target.status_code == 201
    assert client.delete(f"{posts_a}/{delete_target.json()['id']}", headers=headers["admin"]).status_code == 204
    assert client.delete(f"{campaigns_a}/{campaign_id}", headers=headers["admin"]).status_code == 204
