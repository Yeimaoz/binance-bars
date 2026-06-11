"""HTTP get with Binance-aware rate limit + retry handling.

Rules:
- HTTP 429 + Retry-After header → sleep + retry ONCE; second 429 → raise RateLimitedError
- HTTP 418 (IP banned) → raise IpBannedError immediately, do NOT retry
- All other errors propagate via raise_for_status
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30


class RateLimitedError(Exception):
    """Binance returned 429 twice in a row."""


class IpBannedError(Exception):
    """Binance returned 418 — IP banned (do not retry)."""


def get_with_backoff(url: str, params: dict, *, max_retries: int = 1) -> httpx.Response:
    """GET with 429 backoff + 418 immediate raise.

    Returns the successful Response; caller does `.json()` itself.
    """
    last_429: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(url, params=params)
        if resp.status_code == 200:
            return resp
        if resp.status_code == 418:
            raise IpBannedError(f"IP banned by Binance at {url}")
        if resp.status_code == 429:
            last_429 = resp
            raw = resp.headers.get("Retry-After", "1")
            try:
                retry_after = int(raw)
            except ValueError:
                # RFC 7231 allows HTTP-date format (e.g. "Wed, 21 Oct 2025 07:28:00 GMT").
                # We cannot safely parse arbitrary date strings here; fall back to 1 s.
                logger.warning("HTTP 429 Retry-After value %r is not an integer; defaulting to 1s", raw)
                retry_after = 1
            _MAX_RETRY_AFTER = 300  # 5 minutes; protect against server-controlled DoS
            if retry_after > _MAX_RETRY_AFTER:
                logger.warning(
                    "HTTP 429 Retry-After=%d exceeds cap %d; clamping to %d",
                    retry_after, _MAX_RETRY_AFTER, _MAX_RETRY_AFTER,
                )
                retry_after = _MAX_RETRY_AFTER
            logger.warning("HTTP 429 from %s; sleep %ds (attempt %d)",
                           url, retry_after, attempt + 1)
            time.sleep(retry_after)
            continue
        # any other status — propagate via raise_for_status
        resp.raise_for_status()
        return resp
    raise RateLimitedError(
        f"HTTP 429 from {url} after {max_retries + 1} attempts; "
        f"last Retry-After={last_429.headers.get('Retry-After') if last_429 else 'n/a'}"
    )
