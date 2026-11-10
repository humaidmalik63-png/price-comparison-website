"""In-process HTTP rate limiting for the PriceWise AI API (Phase 14 Stage B).

The deployment configuration advertises ``RATE_LIMIT_PER_MINUTE`` (120 in
``render.yaml``), but until now nothing enforced it: the value was read into
``src.config`` and never used, leaving the public API (including the Gemini
proxy endpoints and the evidence upload endpoint) unthrottled.

Implementation
--------------
A dependency-free sliding-window limiter built on the standard library:

* one bucket per client key (authenticated user id when a valid session is
  present, otherwise the client IP address);
* buckets expire automatically, so memory stays bounded;
* responses carry the standard ``X-RateLimit-*`` headers and a
  ``Retry-After`` header when a request is rejected;
* the limiter is skipped for the health probes, so an orchestrator polling
  ``/api/health`` can never be throttled.

This is a per-process limiter. On a multi-instance deployment each instance
enforces the limit independently; a shared store (Redis) would be required
for a global limit, which is documented as a follow-up.
"""

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from src.config import RATE_LIMIT_PER_MINUTE

# Endpoints that must never be throttled (orchestrator liveness probes).
EXEMPT_PATHS = {
    "/api/health",
    "/api/health/live",
    "/api/health/ready",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}

# Buckets older than this are discarded during a sweep.
_BUCKET_TTL_SECONDS = 300
_MAX_TRACKED_CLIENTS = 10_000


class RateLimiter:
    """Thread-safe sliding-window rate limiter keyed by client identity."""

    def __init__(self, requests_per_minute: int = RATE_LIMIT_PER_MINUTE):
        self.requests_per_minute = max(1, int(requests_per_minute))
        self.window_seconds = 60.0
        self._hits: "OrderedDict[str, list]" = OrderedDict()
        self._lock = threading.Lock()

    def _sweep(self, now: float) -> None:
        """Drop buckets that have not been used inside the TTL window."""
        stale = [
            key
            for key, timestamps in self._hits.items()
            if not timestamps or (now - timestamps[-1]) > _BUCKET_TTL_SECONDS
        ]
        for key in stale:
            self._hits.pop(key, None)

    def check(self, client_key: str) -> Tuple[bool, int, int]:
        """Register a request for ``client_key``.

        Returns ``(allowed, remaining, retry_after_seconds)``.
        """
        now = time.monotonic()
        with self._lock:
            self._sweep(now)

            timestamps = self._hits.get(client_key)
            if timestamps is None:
                timestamps = []
                self._hits[client_key] = timestamps

            cutoff = now - self.window_seconds
            timestamps[:] = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self.requests_per_minute:
                retry_after = int(max(1.0, (timestamps[0] + self.window_seconds) - now))
                return False, 0, retry_after

            timestamps.append(now)

            if len(self._hits) > _MAX_TRACKED_CLIENTS:
                # Drop the least recently used bucket to bound memory.
                self._hits.popitem(last=False)

            remaining = self.requests_per_minute - len(timestamps)
            return True, remaining, 0

    def reset(self) -> None:
        """Clear every bucket (used by tests)."""
        with self._lock:
            self._hits.clear()


# Module-level limiter shared by the application.
rate_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)


def client_key_for(request) -> str:
    """Return the rate-limit bucket key for a request.

    Authenticated traffic is bucketed per session credential, so that a shared
    NAT egress cannot exhaust the quota of an individual shopper. Anonymous
    traffic is bucketed per client IP.

    The session token is hashed before it is used as a bucket key, so no
    credential material is retained in memory or written to any log.
    """
    auth_header = request.headers.get("Authorization")
    credential = None
    if auth_header and auth_header.startswith("Bearer "):
        credential = auth_header[7:].strip()
    else:
        credential = request.cookies.get("session_token")

    if credential:
        digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()[:32]
        return f"session:{digest}"

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Render terminates TLS and sets X-Forwarded-For; the first entry is
        # the originating client.
        return f"ip:{forwarded.split(',')[0].strip()}"

    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


def is_exempt(path: str) -> bool:
    """Return True when a path must bypass rate limiting."""
    if path in EXEMPT_PATHS:
        return True
    # Static documentation and health sub-paths.
    return path.startswith("/api/health")


def reset_rate_limiter() -> None:
    """Reset the shared limiter (test helper)."""
    rate_limiter.reset()


def rate_limit_snapshot() -> Dict[str, int]:
    """Return a small diagnostic snapshot (never contains client secrets)."""
    with rate_limiter._lock:  # noqa: SLF001 - intentional internal inspection
        return {
            "tracked_clients": len(rate_limiter._hits),  # noqa: SLF001
            "requests_per_minute": rate_limiter.requests_per_minute,
        }
