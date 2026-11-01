from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore, Lock


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    retry_after: int | None = None


class AssistantRequestLimiter:
    """In-process quota guard for costly assistant requests."""

    def __init__(self, limit: int, window_seconds: int, max_concurrent: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: dict[str, deque[datetime]] = defaultdict(deque)
        self.lock = Lock()
        self.semaphore = BoundedSemaphore(max_concurrent)

    def acquire(self, client: str) -> LimitResult:
        now = datetime.now(timezone.utc)
        with self.lock:
            bucket = self.requests[client]
            cutoff = now - timedelta(seconds=self.window_seconds)
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return LimitResult(False, max(1, int((bucket[0] + timedelta(seconds=self.window_seconds) - now).total_seconds())))
            if not self.semaphore.acquire(blocking=False):
                return LimitResult(False, 1)
            bucket.append(now)
        return LimitResult(True)

    def release(self) -> None:
        self.semaphore.release()
