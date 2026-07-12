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

from docu_studio.common.music_jamendo import (
    DEFAULT_MUSIC_MOOD,
    JamendoMusicProvider,
    TrackCandidate,
)
from docu_studio.shorts.music_library import MUSIC_DIR, select_music_track

_log = logging.getLogger(__name__)


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


def resolve_music_track(
    provider_name: str,
    mood: str,
    max_duration: float,
    jamendo_client_id: str = "",
    seed: int = 0,
) -> tuple[str, str, int | None] | None:
    """Resolve a local, playable music file for *mood*, honoring the
    provider -> local -> none fallback chain. Returns (local_path, label,
    bpm), or None if no provider produced a usable track — callers must
    skip the music bed gracefully in that case. bpm is the resolved
    TrackCandidate's bpm (populated for local-manifest tracks, always None
    for Jamendo)."""
    if provider_name == "jamendo":
        jamendo = JamendoMusicProvider(jamendo_client_id)
        candidates = jamendo.search(mood, max_duration)
        if candidates:
            try:
                path = jamendo.fetch(candidates[0])
                _log.info("Music: using Jamendo track %r", candidates[0].title)
                return path, candidates[0].title, candidates[0].bpm
            except Exception as exc:
                _log.warning("Jamendo: download failed (%s) — falling back to local", exc)
        else:
            _log.info("Jamendo: no usable candidates — falling back to local")

    local = LocalMusicProvider(seed=seed)
    candidates = local.search(mood, max_duration)
    if candidates:
        path = local.fetch(candidates[0])
        _log.info("Music: using local track %r", candidates[0].title)
        return path, candidates[0].title, candidates[0].bpm

    _log.info("Music: no usable track from any provider — skipping music bed")
    return None
