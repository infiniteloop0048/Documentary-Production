"""Music provider abstraction for the Shorts pipeline.

Providers implement search()/fetch(): search(query, max_duration) returns
candidate tracks, fetch(candidate) resolves one to a local, playable file
path. "local" wraps the existing manifest/folder behavior (music_library.py)
unchanged. "jamendo" calls Jamendo's public API (api.jamendo.com/v3.0/tracks)
and downloads into a user-app-data cache, keyed by a filename-safe slug of
the track title so repeated runs don't refetch.

resolve_music_track() is the single entry point callers use. It walks the
configured provider, then always falls back to local, then gives up (None)
— never raising. The music bed is always optional, matching music_library's
existing contract.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from docu_studio.platform_layer import config_dir
from docu_studio.shorts.music_library import MUSIC_DIR, select_music_track

_log = logging.getLogger(__name__)

JAMENDO_API_URL = "https://api.jamendo.com/v3.0/tracks"
DEFAULT_MUSIC_MOOD = "cinematic"

_MUSIC_CACHE_DIRNAME = "shorts_music_cache"
_REQUEST_TIMEOUT = 10.0
# Upper bound on the durationbetween range sent to Jamendo — generous enough
# that "at least the short's duration" never excludes a normal full-length track.
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
    bpm: int | None = None
    source: str = "local"
    local_path: str | None = None


class LocalMusicProvider:
    """Wraps the existing assets/music/ manifest+folder behavior unchanged."""

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed

    def search(self, query: str, max_duration: float) -> list[TrackCandidate]:
        track = select_music_track(seed=self._seed)
        if track is None:
            return []
        return [TrackCandidate(
            title=track.filename,
            duration=max_duration,
            download_url="",
            bpm=track.bpm,
            source="local",
            local_path=str(MUSIC_DIR / track.filename),
        )]

    def fetch(self, candidate: TrackCandidate) -> str:
        if not candidate.local_path:
            raise ValueError("LocalMusicProvider candidate is missing local_path")
        return candidate.local_path


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

        candidates: list[TrackCandidate] = []
        for item in data.get("results", []):
            try:
                candidates.append(TrackCandidate(
                    title=str(item["name"]),
                    duration=float(item["duration"]),
                    download_url=str(item["audiodownload"]),
                    bpm=None,
                    source="jamendo",
                ))
            except (KeyError, TypeError, ValueError):
                continue
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


def resolve_music_track(
    provider_name: str,
    mood: str,
    max_duration: float,
    jamendo_client_id: str = "",
    seed: int = 0,
) -> tuple[str, str] | None:
    """Resolve a local, playable music file for *mood*, honoring the
    provider -> local -> none fallback chain. Returns (local_path, label),
    or None if no provider produced a usable track — callers must skip the
    music bed gracefully in that case."""
    if provider_name == "jamendo":
        jamendo = JamendoMusicProvider(jamendo_client_id)
        candidates = jamendo.search(mood, max_duration)
        if candidates:
            try:
                path = jamendo.fetch(candidates[0])
                _log.info("Music: using Jamendo track %r", candidates[0].title)
                return path, candidates[0].title
            except Exception as exc:
                _log.warning("Jamendo: download failed (%s) — falling back to local", exc)
        else:
            _log.info("Jamendo: no usable candidates — falling back to local")

    local = LocalMusicProvider(seed=seed)
    candidates = local.search(mood, max_duration)
    if candidates:
        path = local.fetch(candidates[0])
        _log.info("Music: using local track %r", candidates[0].title)
        return path, candidates[0].title

    _log.info("Music: no usable track from any provider — skipping music bed")
    return None
