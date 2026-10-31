from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Observation:
    post_id: UUID
    metric_definition_id: UUID
    value: Decimal | None
    captured_at: datetime


@dataclass(frozen=True)
class Variation:
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    inputs: tuple[Observation, ...]
    limitations: tuple[str, ...]


def variation(start: Observation | None, end: Observation | None) -> Variation:
    inputs = tuple(item for item in (start, end) if item is not None)
    if start is None or end is None or start.value is None or end.value is None:
        return Variation(None, None, inputs, ("Missing observation values prevent comparison.",))
    if start.post_id != end.post_id or start.metric_definition_id != end.metric_definition_id:
        return Variation(None, None, inputs, ("Observations must represent the same post and metric.",))
    absolute = end.value - start.value
    if start.value == 0:
        return Variation(absolute, None, inputs, ("Percentage change is unavailable when the initial value is zero.",))
    return Variation(absolute, (absolute / start.value) * Decimal("100"), inputs, ())


def evolution(observations: list[Observation]) -> list[Variation]:
    ordered = sorted(observations, key=lambda item: item.captured_at)
    return [variation(ordered[index - 1], ordered[index]) for index in range(1, len(ordered))]


def observable_engagement_rate(likes: Decimal | None, comments: Decimal | None, denominator: Decimal | None) -> tuple[Decimal | None, tuple[str, ...]]:
    if likes is None or comments is None or denominator is None:
        return None, ("Missing inputs prevent calculating an observable engagement rate.",)
    if denominator <= 0:
        return None, ("A positive, explicitly supplied denominator is required.",)
    return ((likes + comments) / denominator) * Decimal("100"), ("This rate does not represent reach or impressions.",)


def compare_experiments(values: dict[UUID, tuple[Observation | None, Observation | None]]) -> dict[UUID, Variation]:
    return {
        experiment_id: variation(start, end)
        for experiment_id, (start, end) in values.items()
    }
