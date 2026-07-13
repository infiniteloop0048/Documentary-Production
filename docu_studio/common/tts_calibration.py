"""Persisted per-(TTS provider, voice) words-per-minute calibration.

Shared by Shorts and Clip Story (and any future pipeline needing to target a word
count from a duration): the 170 WPM default used for word-target math assumes a
brisk TTS voice; several configured providers/voices actually speak closer to
120-130 WPM. This module stores a rolling measured WPM per provider+voice (JSON
file in the OS config dir, mirroring history/run_history.py's atomic-write
pattern) so script generation can target the pace the configured voice actually
produces.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from docu_studio.platform_layer import config_dir

_log = logging.getLogger(__name__)

_CALIBRATION_FILE = "shorts_tts_calibration.json"

CALIBRATION_MIN_WPM = 90.0
CALIBRATION_MAX_WPM = 220.0

# Exponential moving average weight for each new measurement — smooths out
# per-run noise (short scripts, misdetected silences) while still tracking
# real drift in a voice's pace over time.
_EMA_ALPHA = 0.3


def _clamp(wpm: float) -> float:
    return max(CALIBRATION_MIN_WPM, min(CALIBRATION_MAX_WPM, wpm))


def calibration_key(provider: str, voice: str) -> str:
    return f"{provider}:{voice}"


def _calibration_path() -> Path:
    return config_dir() / _CALIBRATION_FILE


def load_calibration() -> dict[str, float]:
    path = _calibration_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}


def _save_calibration(data: dict[str, float]) -> None:
    path = _calibration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        tmp.write(json.dumps(data, indent=2))
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def get_wpm(provider: str, voice: str, default: float) -> float:
    """Return the stored WPM for *provider*+*voice*, clamped, or *default*."""
    key = calibration_key(provider, voice)
    stored = load_calibration().get(key)
    if stored is None:
        return default
    return _clamp(stored)


def record_measurement(
    provider: str, voice: str, word_count: int, measured_duration_seconds: float
) -> float:
    """Compute actual WPM from a completed synthesis and roll it into the
    stored calibration for *provider*+*voice*. Returns the newly measured
    (unsmoothed) WPM for logging."""
    if word_count <= 0 or measured_duration_seconds <= 0:
        return 0.0
    measured_wpm = word_count / measured_duration_seconds * 60
    key = calibration_key(provider, voice)
    data = load_calibration()
    previous = data.get(key)
    blended = measured_wpm if previous is None else (
        _EMA_ALPHA * measured_wpm + (1 - _EMA_ALPHA) * previous
    )
    data[key] = _clamp(blended)
    try:
        _save_calibration(data)
    except Exception as exc:
        _log.warning("Failed to persist TTS calibration for %s: %s", key, exc)
    return measured_wpm
