import threading
from asyncio import Lock, sleep
from collections import defaultdict
from time import perf_counter, sleep as sync_sleep
from typing import Final

from pyrate_limiter import Limiter, RequestRate, Duration

_GLOBAL_API_LIMIT: Final[int] = 400
bearer_limiter = Limiter(RequestRate(500, Duration.MINUTE))


class GlobalRateLimiter:
    """Endpoint-global ratelimiter. Bol enforces a global ratelimit to each endpoint, besides the normal ratelimit.
    """

    def __init__(self):
        self._interval = 1.0 / _GLOBAL_API_LIMIT
        self._next: float | None = None
        self._async_lock = Lock()
        self._sync_lock = threading.Lock()

    async def acquire_async(self):
        async with self._async_lock:
            now = perf_counter()
            slot = self._next if (self._next is not None and self._next > now) else now
            self._next = slot + self._interval
        delay = slot - perf_counter()
        if delay > 0:
            await sleep(delay)

    def acquire_sync(self):
        with self._sync_lock:
            now = perf_counter()
            slot = self._next if (self._next is not None and self._next > now) else now
            self._next = slot + self._interval
        delay = slot - perf_counter()
        if delay > 0:
            sync_sleep(delay)


_global_limiters: dict[str, GlobalRateLimiter] = defaultdict(GlobalRateLimiter)


async def acquire_global_async(identity: str):
    await _global_limiters[identity].acquire_async()


def acquire_global_sync(identity: str):
    _global_limiters[identity].acquire_sync()
