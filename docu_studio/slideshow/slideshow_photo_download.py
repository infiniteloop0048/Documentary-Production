"""Slideshow topic-fetch orchestration: search + dedup + over-fetch pooling
on top of the shared resilient-download primitives in
docu_studio/common/resilient_download.py.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from urllib.parse import urlparse

from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult
from docu_studio.common.resilient_download import build_download_session, download_resilient

_log = logging.getLogger(__name__)

_MAX_POOL_MULTIPLIER = 1.5


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
            download_resilient(session, photo.url, dest, last_request_at)
            downloaded.append(dest)
        except Exception as exc:
            _log.warning("Failed to download photo %s: %s", photo.url, exc)

    if not downloaded:
        raise RuntimeError(f"Could not download any images for topic '{topic}'.")
    if len(downloaded) < count:
        _log.warning("Fetched %d of %d requested images for topic '%s'", len(downloaded), count, topic)

    return downloaded
