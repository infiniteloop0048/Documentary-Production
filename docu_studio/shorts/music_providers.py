"""Music provider abstraction for the Shorts pipeline.

Providers implement search()/fetch(): search(query, max_duration) returns
candidate tracks, fetch(candidate) resolves one to a local, playable file
path. "local" wraps the existing manifest/folder behavior (music_library.py)
unchanged. "jamendo" calls Jamendo's public API (api.jamendo.com/v3.0/tracks)
and downloads into a user-app-data cache, keyed by a filename-safe slug of
the track title so repeated runs don't refetch.

resolve_music_track() is the single entry point callers use. For the "jamendo"
provider it tries up to 3 LLM-suggested mood tags in order, then a broad
no-tag-filter query as a last resort before giving up on Jamendo (a single
mood tag sometimes has zero matching tracks — Jamendo's tag coverage is
inconsistent). It then always falls back to local, then gives up (None) —
never raising. The music bed is always optional, matching music_library's
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
    moods: list[str],
    max_duration: float,
    jamendo_client_id: str = "",
    seed: int = 0,
) -> tuple[str, str, int | None] | None:
    """Resolve a local, playable music file for one of *moods*, honoring the
    provider -> local -> none fallback chain. Returns (local_path, label,
    bpm), or None if no provider produced a usable track — callers must
    skip the music bed gracefully in that case. bpm is the resolved
    TrackCandidate's bpm (populated for local-manifest tracks, always None
    for Jamendo)."""
    tags = [m for m in moods if m][:3] or [DEFAULT_MUSIC_MOOD]

    if provider_name == "jamendo":
        jamendo = JamendoMusicProvider(jamendo_client_id)
        for tag in tags:
            candidates = jamendo.search(tag, max_duration)
            if not candidates:
                _log.info("Jamendo: no usable candidates for tag %r — trying next tag", tag)
                continue
            try:
                path = jamendo.fetch(candidates[0])
                _log.info("Music: using Jamendo track %r (tag=%r)", candidates[0].title, tag)
                return path, candidates[0].title, candidates[0].bpm
            except Exception as exc:
                _log.warning(
                    "Jamendo: download failed for tag %r (%s) — trying next tag", tag, exc
                )

        # Every mood tag came up empty/failed — try once more with no tag filter
        # at all (searches the whole catalog) before giving up on Jamendo. This
        # is the "never happen that a video has no music" guarantee: a single
        # mood word can legitimately have zero matching tracks, but an unfiltered
        # query over Jamendo's full catalog essentially always returns something.
        _log.info(
            "Jamendo: all %d mood tag(s) exhausted — trying broad fallback query "
            "with no tag filter", len(tags),
        )
        candidates = jamendo.search("", max_duration)
        if candidates:
            try:
                path = jamendo.fetch(candidates[0])
                _log.info(
                    "Music: using Jamendo track %r (broad fallback, no tag filter)",
                    candidates[0].title,
                )
                return path, candidates[0].title, candidates[0].bpm
            except Exception as exc:
                _log.warning(
                    "Jamendo: broad fallback download failed (%s) — falling back to local", exc
                )
        else:
            _log.warning(
                "Jamendo: broad fallback query returned zero candidates — falling back to local"
            )

    local = LocalMusicProvider(seed=seed)
    candidates = local.search(tags[0], max_duration)
    if candidates:
        path = local.fetch(candidates[0])
        _log.info("Music: using local track %r", candidates[0].title)
        return path, candidates[0].title, candidates[0].bpm

    _log.warning("Music: no usable track from any provider — skipping music bed")
    return None
