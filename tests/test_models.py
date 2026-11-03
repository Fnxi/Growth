from app.db.base import Base
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app.db.models import Campaign, MembershipStatus, MetricClassification, Organization, OrganizationRole, OrganizationStatus, PlatformRole, Post, UserStatus, campaign_posts


def test_initial_model_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "campaign_posts",
        "campaigns",
        "distribution_events",
        "experiments",
        "infrastructure_alerts",
        "infrastructure_check_runs",
        "infrastructure_events",
        "infrastructure_scheduler_heartbeat",
        "metric_definitions",
        "organization_memberships",
        "organizations",
        "posts",
        "public_metric_snapshots",
        "tracking_events",
        "tracking_links",
        "users",
        "auth_sessions",
        "refresh_tokens",
        "auth_audit_events",
    }


def test_metric_classifications_are_explicit() -> None:
    assert {classification.value for classification in MetricClassification} == {
        "observed",
        "calculated",
        "estimated",
        "unavailable",
    }


def test_identity_enums_are_explicit() -> None:
    assert {status.value for status in UserStatus} == {"active", "disabled"}
    assert {role.value for role in PlatformRole} == {"standard", "platform_admin"}
    assert {status.value for status in OrganizationStatus} == {"active", "suspended", "archived"}
    assert {role.value for role in OrganizationRole} == {"owner", "admin", "analyst", "viewer"}
    assert {status.value for status in MembershipStatus} == {"active", "suspended", "removed"}


def test_tenancy_metadata_matches_nullable_expansion_migration() -> None:
    configure_mappers()

    for model, foreign_key_name, unique_name, index_name, relationship_name in (
        (Campaign, "fk_campaign_organization", "uq_campaign_id_organization", "ix_campaign_organization_id", "campaigns"),
        (Post, "fk_post_organization", "uq_post_id_organization", "ix_post_organization_id", "posts"),
    ):
        table = model.__table__
        assert table.c.organization_id.nullable
        foreign_key = next(constraint for constraint in table.foreign_key_constraints if constraint.name == foreign_key_name)
        assert tuple(foreign_key.column_keys) == ("organization_id",)
        assert [element.target_fullname for element in foreign_key.elements] == ["organizations.id"]
        assert foreign_key.ondelete == "RESTRICT"
        unique = next(constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint) and constraint.name == unique_name)
        assert tuple(unique.columns.keys()) == ("id", "organization_id")
        assert next(index for index in table.indexes if index.name == index_name).columns.keys() == ["organization_id"]
        assert getattr(Organization, relationship_name).property.back_populates == "organization"
        assert "delete" not in getattr(Organization, relationship_name).property.cascade
        assert "delete-orphan" not in getattr(Organization, relationship_name).property.cascade
        assert model().organization_id is None

    association = campaign_posts
    assert association.c.organization_id.nullable
    assert next(index for index in association.indexes if index.name == "ix_campaign_posts_organization_id").columns.keys() == ["organization_id"]
    expected_foreign_keys = {
        "fk_campaign_post_organization": (("organization_id",), ("organizations.id",), "RESTRICT"),
        "fk_campaign_posts_campaign_organization": (("campaign_id", "organization_id"), ("campaigns.id", "campaigns.organization_id"), "CASCADE"),
        "fk_campaign_posts_post_organization": (("post_id", "organization_id"), ("posts.id", "posts.organization_id"), "CASCADE"),
    }
    for name, (columns, targets, ondelete) in expected_foreign_keys.items():
        foreign_key = next(constraint for constraint in association.foreign_key_constraints if constraint.name == name)
        assert isinstance(foreign_key, ForeignKeyConstraint)
        assert tuple(foreign_key.column_keys) == columns
        assert tuple(element.target_fullname for element in foreign_key.elements) == targets
        assert foreign_key.ondelete == ondelete

    assert Campaign.__table__.c.name.unique
    assert Post.__table__.c.canonical_url.unique
    assert Campaign.posts.property.primaryjoin.compare(Campaign.id == campaign_posts.c.campaign_id)
    assert Campaign.posts.property.secondaryjoin.compare(Post.id == campaign_posts.c.post_id)
    assert Post.campaigns.property.primaryjoin.compare(Post.id == campaign_posts.c.post_id)
    assert Post.campaigns.property.secondaryjoin.compare(Campaign.id == campaign_posts.c.campaign_id)
    assert Campaign.experiments.property.back_populates == "campaign"
    assert "delete-orphan" in Campaign.experiments.property.cascade
    assert Post.metric_snapshots.property.back_populates == "post"
    assert "delete-orphan" in Post.metric_snapshots.property.cascade
