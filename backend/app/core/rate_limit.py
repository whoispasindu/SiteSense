"""In-process sliding-window rate limiter for sensitive endpoints (sign-in, token refresh).

It is per API instance, which is enough for a single container. When the API scales to several
instances (Phase 13), swap the store for Redis behind the same interface.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from app.core.errors import AppError


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please wait a moment and try again."

    def __init__(self, retry_after: int) -> None:
        super().__init__()
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(retry_after)}


class RateLimiter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 50_000) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, key: str, *, limit: int, window_seconds: float = 60.0) -> None:
        """Record one request for ``key``; raise ``RateLimitedError`` if over ``limit``."""
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self._max_keys:
                    self._evict_expired(now, window_seconds)
                hits = self._hits[key] = deque()
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(window_seconds - (now - hits[0])) + 1)
                raise RateLimitedError(retry_after)
            hits.append(now)

    def _evict_expired(self, now: float, window_seconds: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] >= window_seconds]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self._max_keys:
            # Still full of active keys: drop the oldest half rather than grow without bound.
            for key in list(self._hits)[: self._max_keys // 2]:
                del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
