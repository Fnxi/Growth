from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.analytics.metrics import Observation, observable_engagement_rate, variation


def observation(value: str | None, post_id=None) -> Observation:
    return Observation(post_id or uuid4(), uuid4(), Decimal(value) if value is not None else None, datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_increase_and_decrease_are_reproducible() -> None:
    post_id, metric_id = uuid4(), uuid4()
    start = Observation(post_id, metric_id, Decimal("10"), datetime(2026, 1, 1, tzinfo=timezone.utc))
    end = Observation(post_id, metric_id, Decimal("15"), datetime(2026, 1, 2, tzinfo=timezone.utc))
    result = variation(start, end)
    assert result.absolute_change == Decimal("5")
    assert result.percentage_change == Decimal("50.0")
    assert variation(end, start).absolute_change == Decimal("-5")


def test_zero_and_missing_values_are_not_percentages() -> None:
    post_id, metric_id = uuid4(), uuid4()
    zero = Observation(post_id, metric_id, Decimal("0"), datetime(2026, 1, 1, tzinfo=timezone.utc))
    end = Observation(post_id, metric_id, Decimal("2"), datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert variation(zero, end).percentage_change is None
    assert variation(None, end).absolute_change is None


def test_observable_engagement_requires_valid_denominator() -> None:
    rate, limitations = observable_engagement_rate(Decimal("8"), Decimal("2"), Decimal("100"))
    assert rate == Decimal("10.0")
    assert limitations
    assert observable_engagement_rate(Decimal("1"), Decimal("1"), Decimal("0"))[0] is None
