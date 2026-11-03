from __future__ import annotations

import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRE_TENANCY_REVISION = "d8f7a1c4e902"
TENANCY_REVISION = "f1a9c2d5e8b0"
PROHIBITED_DATABASES = {"growth_lab", "growth_lab_demo"}


def isolated_database_url() -> str:
    database_url = os.environ.get("TENANCY_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TENANCY_TEST_DATABASE_URL is required for PostgreSQL migration integration tests.")
    parsed = urlsplit(database_url)
    database_name = parsed.path.lstrip("/")
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"} or not database_name:
        pytest.fail("TENANCY_TEST_DATABASE_URL must identify a PostgreSQL database.")
    if database_name in PROHIBITED_DATABASES:
        pytest.fail("Refusing to run tenancy migration tests against a protected database.")
    if not (database_name.startswith("test_") or database_name.endswith("_test")):
        pytest.fail("TENANCY_TEST_DATABASE_URL must use a dedicated database named test_* or *_test.")
    return database_url


def alembic(database_url: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [str(PROJECT_ROOT / ".venv" / "Scripts" / "alembic.exe"), *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def constraint_exists(connection, name: str) -> bool:
    return bool(
        connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = :name)"),
            {"name": name},
        )
    )


def column_exists(connection, table_name: str, column_name: str) -> bool:
    return bool(
        connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table_name AND column_name = :column_name)"
            ),
            {"table_name": table_name, "column_name": column_name},
        )
    )


def test_tenancy_expansion_preserves_legacy_data_and_enforces_assigned_scope() -> None:
    database_url = isolated_database_url()
    engine = create_engine(database_url)
    legacy_campaign = uuid4()
    legacy_post = uuid4()

    try:
        alembic(database_url, "downgrade", "base")
        alembic(database_url, "upgrade", PRE_TENANCY_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO campaigns (id, name) VALUES (:id, :name)"),
                {"id": legacy_campaign, "name": "legacy-campaign"},
            )
            connection.execute(
                text("INSERT INTO posts (id, canonical_url, platform) VALUES (:id, :url, :platform)"),
                {"id": legacy_post, "url": "https://example.test/legacy", "platform": "instagram"},
            )
            connection.execute(
                text("INSERT INTO campaign_posts (campaign_id, post_id) VALUES (:campaign_id, :post_id)"),
                {"campaign_id": legacy_campaign, "post_id": legacy_post},
            )

        alembic(database_url, "upgrade", TENANCY_REVISION)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM campaigns WHERE id = :id"), {"id": legacy_campaign}) == 1
            assert connection.scalar(text("SELECT count(*) FROM posts WHERE id = :id"), {"id": legacy_post}) == 1
            assert connection.scalar(text("SELECT organization_id IS NULL FROM campaigns WHERE id = :id"), {"id": legacy_campaign}) is True
            assert connection.scalar(text("SELECT organization_id IS NULL FROM posts WHERE id = :id"), {"id": legacy_post}) is True
            assert connection.scalar(text("SELECT organization_id IS NULL FROM campaign_posts WHERE campaign_id = :campaign_id AND post_id = :post_id"), {"campaign_id": legacy_campaign, "post_id": legacy_post}) is True
            for name in ("campaign_posts_campaign_id_fkey", "campaign_posts_post_id_fkey"):
                assert constraint_exists(connection, name)
            for name in (
                "fk_campaign_organization",
                "fk_post_organization",
                "fk_campaign_post_organization",
                "fk_campaign_posts_campaign_organization",
                "fk_campaign_posts_post_organization",
                "uq_campaign_id_organization",
                "uq_post_id_organization",
            ):
                assert constraint_exists(connection, name)

        alembic(database_url, "downgrade", PRE_TENANCY_REVISION)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM campaigns WHERE id = :id"), {"id": legacy_campaign}) == 1
            assert connection.scalar(text("SELECT count(*) FROM posts WHERE id = :id"), {"id": legacy_post}) == 1
            assert connection.scalar(text("SELECT count(*) FROM campaign_posts WHERE campaign_id = :campaign_id AND post_id = :post_id"), {"campaign_id": legacy_campaign, "post_id": legacy_post}) == 1
            assert not column_exists(connection, "campaigns", "organization_id")
            assert not column_exists(connection, "posts", "organization_id")
            assert not column_exists(connection, "campaign_posts", "organization_id")

        alembic(database_url, "upgrade", TENANCY_REVISION)
        organization_a = uuid4()
        organization_b = uuid4()
        campaign_a = uuid4()
        campaign_b = uuid4()
        post_a = uuid4()
        post_b = uuid4()
        cascade_campaign = uuid4()
        cascade_post = uuid4()
        cascade_experiment = uuid4()
        with engine.begin() as connection:
            for organization_id, name, slug in ((organization_a, "Organization A", "organization-a"), (organization_b, "Organization B", "organization-b")):
                connection.execute(
                    text("INSERT INTO organizations (id, name, slug_normalized, status) VALUES (:id, :name, :slug, 'active')"),
                    {"id": organization_id, "name": name, "slug": slug},
                )
            connection.execute(text("UPDATE campaigns SET organization_id = :organization_id WHERE id = :id"), {"organization_id": organization_a, "id": legacy_campaign})
            connection.execute(text("UPDATE posts SET organization_id = :organization_id WHERE id = :id"), {"organization_id": organization_a, "id": legacy_post})
            connection.execute(text("UPDATE campaign_posts SET organization_id = :organization_id WHERE campaign_id = :campaign_id AND post_id = :post_id"), {"organization_id": organization_a, "campaign_id": legacy_campaign, "post_id": legacy_post})
            connection.execute(text("INSERT INTO campaigns (id, name, organization_id) VALUES (:id, :name, :organization_id)"), {"id": campaign_a, "name": "campaign-a", "organization_id": organization_a})
            connection.execute(text("INSERT INTO posts (id, canonical_url, platform, organization_id) VALUES (:id, :url, :platform, :organization_id)"), {"id": post_a, "url": "https://example.test/a", "platform": "instagram", "organization_id": organization_a})
            connection.execute(text("INSERT INTO campaign_posts (campaign_id, post_id, organization_id) VALUES (:campaign_id, :post_id, :organization_id)"), {"campaign_id": campaign_a, "post_id": post_a, "organization_id": organization_a})
            connection.execute(text("INSERT INTO campaigns (id, name, organization_id) VALUES (:id, :name, :organization_id)"), {"id": campaign_b, "name": "campaign-b", "organization_id": organization_a})
            connection.execute(text("INSERT INTO posts (id, canonical_url, platform, organization_id) VALUES (:id, :url, :platform, :organization_id)"), {"id": post_b, "url": "https://example.test/b", "platform": "instagram", "organization_id": organization_b})
            connection.execute(text("INSERT INTO campaigns (id, name, organization_id) VALUES (:id, :name, :organization_id)"), {"id": cascade_campaign, "name": "cascade-campaign", "organization_id": organization_b})
            connection.execute(text("INSERT INTO posts (id, canonical_url, platform, organization_id) VALUES (:id, :url, :platform, :organization_id)"), {"id": cascade_post, "url": "https://example.test/cascade", "platform": "instagram", "organization_id": organization_b})
            connection.execute(text("INSERT INTO campaign_posts (campaign_id, post_id, organization_id) VALUES (:campaign_id, :post_id, :organization_id)"), {"campaign_id": cascade_campaign, "post_id": cascade_post, "organization_id": organization_b})
            connection.execute(text("INSERT INTO experiments (id, campaign_id, name, hypothesis, variable, method, starts_at) VALUES (:id, :campaign_id, :name, :hypothesis, :variable, :method, now())"), {"id": cascade_experiment, "campaign_id": cascade_campaign, "name": "cascade-experiment", "hypothesis": "h", "variable": "v", "method": "m"})

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO campaign_posts (campaign_id, post_id, organization_id) VALUES (:campaign_id, :post_id, :organization_id)"), {"campaign_id": campaign_b, "post_id": post_b, "organization_id": organization_a})
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO campaign_posts (campaign_id, post_id, organization_id) VALUES (:campaign_id, :post_id, :organization_id)"), {"campaign_id": campaign_a, "post_id": post_a, "organization_id": uuid4()})
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": organization_a})
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO campaigns (id, name, organization_id) VALUES (:id, :name, :organization_id)"), {"id": uuid4(), "name": "campaign-a", "organization_id": organization_b})
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO posts (id, canonical_url, platform, organization_id) VALUES (:id, :url, :platform, :organization_id)"), {"id": uuid4(), "url": "https://example.test/a", "platform": "instagram", "organization_id": organization_b})
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM campaigns WHERE id = :id"), {"id": cascade_campaign})
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM campaign_posts WHERE campaign_id = :id"), {"id": cascade_campaign}) == 0
            assert connection.scalar(text("SELECT count(*) FROM experiments WHERE id = :id"), {"id": cascade_experiment}) == 0
    finally:
        engine.dispose()
