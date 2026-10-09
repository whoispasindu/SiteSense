import pytest

from app.core.rate_limit import RateLimitedError, RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_blocks_with_retry_after() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(3):
        limiter.hit("login:1.2.3.4", limit=3)
    with pytest.raises(RateLimitedError) as exc:
        limiter.hit("login:1.2.3.4", limit=3)

    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "61"}


def test_window_slides() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    for _ in range(3):
        limiter.hit("k", limit=3)

    clock.now += 60
    limiter.hit("k", limit=3)  # oldest hits have left the window


def test_keys_are_independent() -> None:
    limiter = RateLimiter(clock=FakeClock())
    limiter.hit("a", limit=1)
    limiter.hit("b", limit=1)
    with pytest.raises(RateLimitedError):
        limiter.hit("a", limit=1)


def test_memory_is_bounded() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, max_keys=10)
    for i in range(10):
        limiter.hit(f"k{i}", limit=5)
    clock.now += 120
    limiter.hit("new", limit=5)  # stale keys are evicted first
    assert len(limiter._hits) == 1

    for i in range(20):
        limiter.hit(f"busy{i}", limit=5)
    assert len(limiter._hits) <= 10


def test_reset_clears_state() -> None:
    limiter = RateLimiter(clock=FakeClock())
    limiter.hit("k", limit=1)
    limiter.reset()
    limiter.hit("k", limit=1)
