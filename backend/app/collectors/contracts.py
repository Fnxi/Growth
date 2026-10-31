from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, HttpUrl


class CollectedMetric(BaseModel):
    metric_name: str
    value: Decimal
    captured_at: datetime
    evidence_reference: HttpUrl | None = None


class MetricCollector(Protocol):
    source_name: str

    def collect_public_metrics(self, canonical_url: str) -> list[CollectedMetric]:
        """Return normalized data from an authorized source only."""
