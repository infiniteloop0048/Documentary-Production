"""Resilient photo downloads for the Slideshow topic-fetch flow — a
self-contained copy of the hardened pattern in
docu_studio/shorts/shorts_footage_download.py (session + browser UA,
(10, 30)s connect/read timeouts, retry with backoff+jitter on transient
failures only, same-host pacing). Not imported from shorts/, per the Phase 1
design decision to defer all shared infrastructure extraction with shorts/
until a phase actually needs it.
"""
from __future__ import annotations

import logging
import math
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult

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
_MAX_POOL_MULTIPLIER = 1.5


def build_download_session() -> requests.Session:
    """One Session per fetch's worth of downloads, for connection pooling/reuse."""
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_USER_AGENT})
    return session


def _is_retriable(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        return response is not None and response.status_code in _RETRIABLE_STATUS_CODES
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def download_photo_resilient(
    session: requests.Session,
    url: str,
    dest: str,
    last_request_at: dict[str, float] | None = None,
) -> str:
    """Download *url* to *dest*, retrying transient failures (connection
    resets, timeouts, 5xx/429) with exponential backoff + jitter. Client
    errors (4xx other than 429) are not retried. If *last_request_at* is
    given, paces sequential requests to the same host with a small random
    delay. Raises the final exception if all attempts are exhausted.
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


def _dedup_key(photo: PhotoResult) -> str:
    return photo.photo_id if photo.photo_id else photo.url


def fetch_topic_images(
    topic: str, count: int, providers: list[PhotoProvider], dest_dir: Path,
) -> list[str]:
    """Search *providers* in order for *topic*, download up to *count* distinct
    photos into *dest_dir*, and return the local file paths of whichever
    downloads succeeded (in pool order).

    Over-fetches a candidate pool capped at ceil(count * 1.5) — the same
    guard shorts_assembly.py uses for footage — so a few failed downloads
    don't require a second round-trip to the providers. Raises RuntimeError
    if zero photos download successfully; returns fewer than *count* (with a
    warning logged) if the pool runs out before reaching it.
    """
    if count <= 0:
        raise ValueError("count must be positive")

    max_pool = math.ceil(count * _MAX_POOL_MULTIPLIER)
    seen: dict[str, PhotoResult] = {}
    for provider in providers:
        if len(seen) >= max_pool:
            break
        try:
            results = provider.search(topic, page=1)
        except Exception as exc:
            _log.warning("%s: search failed: %s", type(provider).__name__, exc)
            continue
        for photo in results:
            key = _dedup_key(photo)
            if key and key not in seen:
                seen[key] = photo
            if len(seen) >= max_pool:
                break

    pool = list(seen.values())[:max_pool]
    dest_dir.mkdir(parents=True, exist_ok=True)
    session = build_download_session()
    last_request_at: dict[str, float] = {}

    downloaded: list[str] = []
    for i, photo in enumerate(pool):
        if len(downloaded) >= count:
            break
        ext = Path(urlparse(photo.url).path).suffix or ".jpg"
        dest = str(dest_dir / f"topic_{i:03d}{ext}")
        try:
            download_photo_resilient(session, photo.url, dest, last_request_at)
            downloaded.append(dest)
        except Exception as exc:
            _log.warning("Failed to download photo %s: %s", photo.url, exc)

    if not downloaded:
        raise RuntimeError(f"Could not download any images for topic '{topic}'.")
    if len(downloaded) < count:
        _log.warning("Fetched %d of %d requested images for topic '%s'", len(downloaded), count, topic)

    return downloaded
