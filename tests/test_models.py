from app.db.base import Base
from app.db.models import MetricClassification


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
        "posts",
        "public_metric_snapshots",
        "tracking_events",
        "tracking_links",
    }


def test_metric_classifications_are_explicit() -> None:
    assert {classification.value for classification in MetricClassification} == {
        "observed",
        "calculated",
        "estimated",
        "unavailable",
    }
