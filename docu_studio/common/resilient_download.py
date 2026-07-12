"""Shared resilient-HTTP-download primitives for footage/photo fetching.

Real runs observed intermittent ConnectionResetError(104, 'Connection reset
by peer') and RemoteDisconnected failures against videos.pexels.com,
cdn.pixabay.com, and images.pexels.com, especially when several downloads
fire in quick succession. Direct reproduction confirmed the resets are real
and not tied to a single cause (occurred with and without a shared session,
with library and browser User-Agents, both mid-burst and as a lone first
request) — so this applies the standard resilience pattern (session reuse,
retry with backoff+jitter on transient failures only, same-host pacing)
rather than a narrow workaround. Used by both the Shorts and Slideshow
pipelines' footage/photo download call sites.

This is a Shorts/Slideshow-only concern: the documentary pipeline's own
`pipeline.stages.footage_assembly.download_clip` is untouched.
"""
from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

import requests

_log = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CONNECT_TIMEOUT_SECONDS = 10
_READ_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.5
_BACKOFF_JITTER_SECONDS = (0.0, 0.5)
_RETRIABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_SAME_HOST_DELAY_RANGE_SECONDS = (0.2, 0.5)


def build_download_session() -> requests.Session:
    """One Session per run's worth of downloads, for connection pooling/reuse."""
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_USER_AGENT})
    return session


def _is_retriable(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        return response is not None and response.status_code in _RETRIABLE_STATUS_CODES
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def download_resilient(
    session: requests.Session,
    url: str,
    dest: str,
    last_request_at: dict[str, float] | None = None,
) -> str:
    """Download *url* to *dest*, retrying transient failures (connection
    resets, timeouts, 5xx/429) with exponential backoff + jitter. Client
    errors (4xx other than 429) are not retried. If *last_request_at* is
    given, paces sequential requests to the same host with a small random
    delay to avoid bursting past whatever triggers upstream resets. Raises
    the final exception if all attempts are exhausted.
    """
    host = urlparse(url).netloc
    if last_request_at is not None:
        last = last_request_at.get(host)
        if last is not None:
            min_gap = random.uniform(*_SAME_HOST_DELAY_RANGE_SECONDS)
            remaining = min_gap - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        if last_request_at is not None:
            last_request_at[host] = time.monotonic()
        try:
            with session.get(
                url, stream=True,
                timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
            ) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
            return dest
        except Exception as exc:
            if attempt >= _MAX_ATTEMPTS or not _is_retriable(exc):
                raise
            backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(*_BACKOFF_JITTER_SECONDS)
            _log.info(
                "download attempt %d/%d for %s after %s, retrying in %.1fs",
                attempt, _MAX_ATTEMPTS, url, type(exc).__name__, backoff,
            )
            time.sleep(backoff)
    raise AssertionError("unreachable")  # pragma: no cover
