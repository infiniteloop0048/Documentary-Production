"""Loader for the shorts music-bed manifest (assets/music/manifest.json).

Ships with a placeholder-only manifest — no copyrighted audio is bundled.
Users drop their own royalty-free tracks into assets/music/ per the README
there. Every failure mode here (missing dir, malformed JSON, entry pointing
at a file that was never dropped in) resolves to an empty track list, never
an exception — the music bed is always optional.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

MUSIC_DIR = Path(__file__).parent / "assets" / "music"
MANIFEST_PATH = MUSIC_DIR / "manifest.json"


@dataclass(frozen=True)
class MusicTrack:
    filename: str
    mood: str
    bpm: int


def load_manifest(manifest_path: Path | None = None) -> list[MusicTrack]:
    """Return the MusicTrack entries whose backing audio file actually exists
    on disk. See module docstring for the graceful-empty-list contract."""
    path = manifest_path or MANIFEST_PATH
    if not path.exists():
        _log.info("Music manifest not found at %s — skipping music bed", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning(
            "Music manifest at %s is unreadable/malformed (%s) — skipping music bed",
            path, exc,
        )
        return []

    tracks: list[MusicTrack] = []
    for entry in raw.get("tracks", []):
        try:
            filename = entry["filename"]
            mood = entry["mood"]
            bpm = int(entry["bpm"])
        except (KeyError, TypeError, ValueError):
            _log.warning("Music manifest entry malformed, skipping: %s", entry)
            continue
        if not (path.parent / filename).exists():
            _log.info(
                "Music track %s listed in manifest but not found on disk — skipping",
                filename,
            )
            continue
        tracks.append(MusicTrack(filename=filename, mood=mood, bpm=bpm))
    return tracks


def select_music_track(seed: int, manifest_path: Path | None = None) -> MusicTrack | None:
    """Return a reproducible (seeded) track from the manifest, or None if no
    usable track exists — callers must skip the music bed gracefully then."""
    tracks = load_manifest(manifest_path)
    if not tracks:
        return None
    return random.Random(seed).choice(tracks)
