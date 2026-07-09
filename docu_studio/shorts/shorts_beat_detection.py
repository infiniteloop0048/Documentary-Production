"""Librosa-based beat-grid detection, isolated in its own module so the
heavier numpy/scipy/numba import chain only loads when beat-sync is enabled
and a music track is actually available (see capability_resolvers.py's
resolve_beat_grid, which calls this as Tier A of its resolver chain)."""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def detect_beats_librosa(track_path: str) -> list[float] | None:
    """Return beat times (seconds) for *track_path* via librosa onset/beat
    tracking, or None if librosa is unavailable or detection fails/yields
    fewer than 2 beats — callers must fall through to a lower tier."""
    try:
        import librosa
    except Exception as exc:
        _log.info("librosa unavailable (%s) — beat detection skipped", exc)
        return None
    try:
        y, sr = librosa.load(track_path, sr=None, mono=True)
        _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    except Exception as exc:
        _log.info("librosa beat detection failed for %s (%s)", track_path, exc)
        return None
    times = [round(float(t), 2) for t in beat_times]
    return times if len(times) >= 2 else None
