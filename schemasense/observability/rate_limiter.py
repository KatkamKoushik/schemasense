"""Thread-Safe Sliding-Window Rate Limiter for SchemaSense 2.0 API Gateway.

Protects against denial of service, resource exhaustion, and high-frequency
unauthorized polling on sensitive agent endpoints.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Tuple


class RateLimiter:
    """Sliding-window rate limiter per client key."""

    def __init__(
        self,
        default_limit_per_minute: int = 120,
        window_seconds: float = 60.0,
    ) -> None:
        self.default_limit = default_limit_per_minute
        self.window_seconds = window_seconds
        self._records: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(
        self,
        key: str,
        limit: int | None = None,
        now: float | None = None,
    ) -> Tuple[bool, int, int]:
        """Checks if a request under `key` is allowed.

        Args:
            key: Unique client/tenant identifier.
            limit: Maximum allowed requests within the sliding window.
            now: Current timestamp (injected for deterministic testing).

        Returns:
            Tuple of (is_allowed: bool, remaining: int, reset_seconds: int)
        """
        current_time = time.time() if now is None else now
        effective_limit = limit if limit is not None else self.default_limit
        cutoff = current_time - self.window_seconds

        with self._lock:
            timestamps = self._records.get(key, [])
            # Prune expired timestamps outside the sliding window
            valid_timestamps = [t for t in timestamps if t > cutoff]

            if len(valid_timestamps) >= effective_limit:
                # Quota exceeded; calculate time until the earliest request slides out
                earliest = valid_timestamps[0]
                reset_seconds = max(
                    1, int(math.ceil(self.window_seconds - (current_time - earliest)))
                )
                self._records[key] = valid_timestamps
                return False, 0, reset_seconds

            # Request permitted; record timestamp
            valid_timestamps.append(current_time)
            self._records[key] = valid_timestamps
            remaining = effective_limit - len(valid_timestamps)
            reset_seconds = int(self.window_seconds)
            return True, remaining, reset_seconds

    def reset(self) -> None:
        """Clears all rate limit records (for test isolation)."""
        with self._lock:
            self._records.clear()


_GLOBAL_RATE_LIMITER: RateLimiter | None = None


def get_platform_rate_limiter(limit_per_minute: int = 120) -> RateLimiter:
    """Retrieves or creates the global singleton rate limiter."""
    global _GLOBAL_RATE_LIMITER
    if _GLOBAL_RATE_LIMITER is None:
        _GLOBAL_RATE_LIMITER = RateLimiter(default_limit_per_minute=limit_per_minute)
    return _GLOBAL_RATE_LIMITER
