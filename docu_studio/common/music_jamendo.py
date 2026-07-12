"""Shared Jamendo music-provider client + cache primitives.

Used by both the Shorts and Slideshow pipelines' music-provider abstractions
(docu_studio.shorts.music_providers, docu_studio.slideshow.slideshow_music).
Each feature keeps its own local-source provider and resolve_music_track()
fallback chain — only the Jamendo API client and the on-disk cache it shares
are common.

Cache-dir note: both features now read/write the SAME cache directory
(<config_dir>/music_cache/) — a Jamendo track downloaded by one feature is a
cache hit for the other if the track title matches. Prior to this module's
introduction, Shorts and Slideshow used separate `shorts_music_cache`/
`slideshow_music_cache` directories; those two caches were structurally
compatible (same key-derivation scheme via safe_cache_filename(title), same
stored format — raw response bytes), so unifying them is a safe merge, not a
data migration. Any `shorts_music_cache/`/`slideshow_music_cache/` directory
left over from before this change is orphaned, not cleaned up automatically.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from docu_studio.platform_layer import config_dir

_log = logging.getLogger(__name__)

JAMENDO_API_URL = "https://api.jamendo.com/v3.0/tracks"
DEFAULT_MUSIC_MOOD = "cinematic"

_MUSIC_CACHE_DIRNAME = "music_cache"
_REQUEST_TIMEOUT = 10.0
# Upper bound on the duration between range sent to Jamendo — generous enough
# that "at least the target duration" never excludes a normal full-length track.
_MAX_TRACK_DURATION = 1200


def music_cache_dir() -> Path:
    return config_dir() / _MUSIC_CACHE_DIRNAME


def safe_cache_filename(title: str, ext: str = "mp3") -> str:
    """Return a filesystem-safe, lowercase cache filename derived from *title*."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_").lower()
    return f"{slug or 'track'}.{ext}"


@dataclass(frozen=True)
class TrackCandidate:
    title: str
    duration: float
    download_url: str
    source: str
    bpm: int | None = None
    local_path: str | None = None


class JamendoMusicProvider:
    """Searches/downloads instrumental tracks from Jamendo's public API.
    Requires a free client_id (https://developer.jamendo.com)."""

    def __init__(self, client_id: str, timeout: float = _REQUEST_TIMEOUT) -> None:
        self._client_id = client_id
        self._timeout = timeout

    def search(self, query: str, max_duration: float) -> list[TrackCandidate]:
        if not self._client_id:
            _log.warning("Jamendo: no client_id configured — skipping search")
            return []
        params = {
            "client_id": self._client_id,
            "format": "json",
            "limit": 10,
            "tags": query,
            "durationbetween": f"{max(1, int(max_duration))}_{_MAX_TRACK_DURATION}",
            "vocalinstrumental": "instrumental",
            "audioformat": "mp31",
        }
        try:
            response = requests.get(JAMENDO_API_URL, params=params, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            _log.warning("Jamendo: search request failed (%s)", exc)
            return []

        raw_results = data.get("results", [])
        candidates: list[TrackCandidate] = []
        for item in raw_results:
            # Jamendo tracks can have downloads disabled by the artist — the item
            # still comes back with a `audiodownload` key, but it's an empty string
            # (and `audiodownload_allowed` is False) rather than the key being
            # absent, so the old bare-KeyError guard let empty URLs through and
            # fetch() crashed with "Invalid URL '': No scheme supplied".
            download_url = item.get("audiodownload") or ""
            if not download_url:
                continue
            try:
                candidates.append(TrackCandidate(
                    title=str(item["name"]),
                    duration=float(item["duration"]),
                    download_url=str(download_url),
                    source="jamendo",
                ))
            except (KeyError, TypeError, ValueError):
                continue
        _log.info(
            "Jamendo: query %r returned %d raw candidates, %d with a usable download URL",
            query, len(raw_results), len(candidates),
        )
        if not candidates:
            _log.info("Jamendo: zero usable results for query %r", query)
        return candidates

    def fetch(self, candidate: TrackCandidate) -> str:
        cache_dir = music_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / safe_cache_filename(candidate.title)
        if dest.exists():
            _log.info("Jamendo: cache hit for %r", candidate.title)
            return str(dest)
        response = requests.get(candidate.download_url, timeout=self._timeout)
        response.raise_for_status()
        dest.write_bytes(response.content)
        _log.info("Jamendo: downloaded %r -> %s", candidate.title, dest)
        return str(dest)
