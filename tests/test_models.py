from app.db.base import Base
from app.db.models import MembershipStatus, MetricClassification, OrganizationRole, OrganizationStatus, PlatformRole, UserStatus


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
