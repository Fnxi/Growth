from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Lock


class AuthRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: dict[str, deque[datetime]] = defaultdict(deque)
        self.lock = Lock()

    def allow(self, *values: str) -> int | None:
        now = datetime.now(timezone.utc)
        keys = [sha256(value.encode("utf-8")).hexdigest() for value in values]
        with self.lock:
            retry_after = 0
            for key in keys:
                bucket = self.requests[key]
                cutoff = now - timedelta(seconds=self.window_seconds)
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if len(bucket) >= self.limit:
                    retry_after = max(retry_after, max(1, int((bucket[0] + timedelta(seconds=self.window_seconds) - now).total_seconds())))
            if retry_after:
                return retry_after
            for key in keys:
                self.requests[key].append(now)
        return None
