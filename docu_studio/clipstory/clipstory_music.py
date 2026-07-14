"""Music provider abstraction for Clip Story — a verbatim copy of
docu_studio.slideshow.slideshow_music's shape (LocalFolderMusicProvider,
resolve_music_track), deliberately not shared with Slideshow: the shared-core
extraction already decided each feature's "local" music concept differs
(Shorts' bundled manifest vs. a user-browsed folder) and isn't worth unifying.
Jamendo search+cache+fetch (JamendoMusicProvider, TrackCandidate) comes from
the shared docu_studio.common.music_jamendo module — that part IS shared.

resolve_music_track() is the single entry point callers use. It walks the
configured provider, falls back to the local folder, then gives up (None) —
never raising. The music bed is always optional.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

from docu_studio.common.music_jamendo import (
    DEFAULT_MUSIC_MOOD,
    JamendoMusicProvider,
    TrackCandidate,
)

_log = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}


class LocalFolderMusicProvider:
    """Picks a random audio file from a user-browsed folder. search() never
    raises — a missing/empty folder or a folder with no recognized audio
    files just returns an empty candidate list."""

    def __init__(self, folder_path: str, seed: int = 0) -> None:
        self._folder_path = folder_path
        self._seed = seed

    def search(self, query: str, max_duration: float) -> list[TrackCandidate]:
        folder = Path(self._folder_path) if self._folder_path else None
        if folder is None:
            return []
        try:
            if not folder.is_dir():
                return []
            files = sorted(
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
            )
        except OSError as exc:
            _log.warning("LocalFolderMusicProvider: search failed (%s) — returning empty list", exc)
            return []
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
                _log.info("Clip Story music: using Jamendo track %r", candidates[0].title)
                return path, candidates[0].title
            except Exception as exc:
                _log.warning("Jamendo: download failed (%s) — falling back to local folder", exc)
        else:
            _log.info("Jamendo: no usable candidates — falling back to local folder")

    local = LocalFolderMusicProvider(local_folder, seed=seed)
    candidates = local.search(mood, max_duration)
    if candidates:
        path = local.fetch(candidates[0])
        _log.info("Clip Story music: using local-folder track %r", candidates[0].title)
        return path, candidates[0].title

    _log.info("Clip Story music: no usable track from any provider — skipping music bed")
    return None
