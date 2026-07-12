"""Music provider abstraction for Slideshow.

Providers implement search()/fetch(): search(query, max_duration) returns
candidate tracks, fetch(candidate) resolves one to a local, playable file
path. Same Jamendo search+cache+fetch technique as
docu_studio.shorts.music_providers, reimplemented self-contained (own
TrackCandidate, own cache dir) per the Phase 1 design decision to keep
slideshow/ free of imports from shorts/. LocalFolderMusicProvider wraps a
user-browsed folder rather than Shorts' bundled assets/music/ manifest, since
Slideshow ships no bundled tracks (Phase 3 design decision).

resolve_music_track() is the single entry point callers use. It walks the
configured provider, falls back to the local folder, then gives up (None) —
never raising. The music bed is always optional.
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from docu_studio.platform_layer import config_dir

_log = logging.getLogger(__name__)

JAMENDO_API_URL = "https://api.jamendo.com/v3.0/tracks"
DEFAULT_MUSIC_MOOD = "cinematic"

_MUSIC_CACHE_DIRNAME = "slideshow_music_cache"
_REQUEST_TIMEOUT = 10.0
# Upper bound on the duration between range sent to Jamendo — generous enough
# that "at least the slideshow's duration" never excludes a normal track.
_MAX_TRACK_DURATION = 1200
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}


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
    source: str = "local_folder"
    local_path: str | None = None


class LocalFolderMusicProvider:
    """Picks a random audio file from a user-browsed folder. search() never
    raises — a missing/empty folder or a folder with no recognized audio
    files just returns an empty candidate list."""

    def __init__(self, folder_path: str, seed: int = 0) -> None:
        self._folder_path = folder_path
        self._seed = seed

    def search(self, query: str, max_duration: float) -> list[TrackCandidate]:
        folder = Path(self._folder_path) if self._folder_path else None
        if folder is None or not folder.is_dir():
            return []
        files = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
        )
        if not files:
            return []
        chosen = random.Random(self._seed).choice(files)
        return [TrackCandidate(
            title=chosen.name,
            duration=max_duration,
            download_url="",
            source="local_folder",
            local_path=str(chosen),
        )]

    def fetch(self, candidate: TrackCandidate) -> str:
        if not candidate.local_path:
            raise ValueError("LocalFolderMusicProvider candidate is missing local_path")
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

        raw_results = data.get("results", [])
        candidates: list[TrackCandidate] = []
        for item in raw_results:
            # Jamendo tracks can have downloads disabled by the artist — the
            # item still comes back with an `audiodownload` key, but it's an
            # empty string rather than the key being absent.
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
    local_folder: str = "",
    seed: int = 0,
) -> tuple[str, str] | None:
    """Resolve a local, playable music file, honoring the provider -> local
    folder -> none fallback chain. Returns (local_path, label), or None if no
    provider produced a usable track — callers must skip the music bed
    gracefully in that case."""
    if provider_name == "jamendo":
        jamendo = JamendoMusicProvider(jamendo_client_id)
        candidates = jamendo.search(mood, max_duration)
        if candidates:
            try:
                path = jamendo.fetch(candidates[0])
                _log.info("Music: using Jamendo track %r", candidates[0].title)
                return path, candidates[0].title
            except Exception as exc:
                _log.warning("Jamendo: download failed (%s) — falling back to local folder", exc)
        else:
            _log.info("Jamendo: no usable candidates — falling back to local folder")

    local = LocalFolderMusicProvider(local_folder, seed=seed)
    candidates = local.search(mood, max_duration)
    if candidates:
        path = local.fetch(candidates[0])
        _log.info("Music: using local-folder track %r", candidates[0].title)
        return path, candidates[0].title

    _log.info("Music: no usable track from any provider — skipping music bed")
    return None
