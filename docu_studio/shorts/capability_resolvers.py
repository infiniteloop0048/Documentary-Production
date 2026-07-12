"""3-tier resolver chain for word-level timing in shorts assembly.

Tier 1: native TTS timestamps, only if the configured TTS adapter exposes them.
Tier 2: Whisper-based forced alignment (docu_studio.shorts.shorts_alignment).
Tier 3: estimated timing — words distributed across the measured audio duration,
weighted by word character length.
"""
from __future__ import annotations

import logging

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.common.captions import WordTiming, estimate_word_timestamps
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_log = logging.getLogger(__name__)


def _tier1_native_timestamps(
    tts_adapter: TTSProvider, script_text: str, audio_path: str
) -> list[WordTiming] | None:
    """Return native word timestamps if *tts_adapter* exposes a get_word_timestamps()
    method, else None. As of this writing, none of gtts/elevenlabs/deepgram expose
    this — this wraps whatever a future adapter provides without editing adapters."""
    getter = getattr(tts_adapter, "get_word_timestamps", None)
    if not callable(getter):
        return None
    try:
        raw = getter(script_text, audio_path)
    except Exception as exc:
        _log.warning("Tier 1 native timestamp call failed: %s", exc)
        return None
    if not raw:
        return None
    return [WordTiming(word=w, start=s, end=e) for w, s, e in raw]


def _tier2_whisper_alignment(audio_path: str, script_text: str) -> list[WordTiming]:
    from docu_studio.shorts.shorts_alignment import run_tier2_alignment

    timings, fraction_matched = run_tier2_alignment(audio_path, script_text)
    _log.info(
        "Tier 2 whisper alignment: %.0f%% of words matched directly, %.0f%% interpolated",
        fraction_matched * 100, (1 - fraction_matched) * 100,
    )
    return timings


def get_word_timestamps(
    audio_path: str, script_text: str, tts_adapter: TTSProvider
) -> tuple[list[WordTiming], str]:
    """Return (timestamps, tier_used) for *script_text* aligned to *audio_path*."""
    tier1 = _tier1_native_timestamps(tts_adapter, script_text, audio_path)
    if tier1 is not None:
        _log.info("get_word_timestamps: using Tier 1 (native TTS timestamps)")
        return tier1, "tier1_native"

    try:
        timings = _tier2_whisper_alignment(audio_path, script_text)
        _log.info("get_word_timestamps: using Tier 2 (Whisper forced alignment)")
        return timings, "tier2_whisper"
    except Exception as exc:
        _log.warning(
            "get_word_timestamps: Tier 2 failed (%s) — falling back to Tier 3", exc
        )

    duration = FFmpegWrapper().get_duration(audio_path)
    _log.info("get_word_timestamps: using Tier 3 (estimated timing)")
    return estimate_word_timestamps(script_text, duration), "tier3_estimated"


def _tier_b_bpm_grid(bpm: int | None, duration: float) -> list[float] | None:
    if not bpm or bpm <= 0 or duration <= 0:
        return None
    interval = 60.0 / bpm
    times: list[float] = []
    t = 0.0
    while t <= duration:
        times.append(round(t, 2))
        t += interval
    return times if len(times) >= 2 else None


def resolve_beat_grid(
    track_path: str, bpm: int | None, duration: float
) -> tuple[list[float] | None, str]:
    """Return (beat_times, tier) for *track_path*: Tier A is librosa beat
    detection on the audio itself; Tier B is a fixed grid derived from
    *bpm* (the resolved TrackCandidate's bpm or the local manifest's bpm);
    Tier C is no grid at all, meaning callers should leave cuts unchanged."""
    try:
        from docu_studio.shorts.shorts_beat_detection import detect_beats_librosa
        grid = detect_beats_librosa(track_path)
    except Exception as exc:
        _log.info("resolve_beat_grid: librosa tier raised (%s) — trying bpm tier", exc)
        grid = None
    if grid is not None:
        _log.info("resolve_beat_grid: using librosa beat detection (%d beats)", len(grid))
        return grid, "librosa"

    grid = _tier_b_bpm_grid(bpm, duration)
    if grid is not None:
        _log.info("resolve_beat_grid: using BPM-metadata grid (bpm=%s, %d beats)", bpm, len(grid))
        return grid, "bpm_metadata"

    _log.info("resolve_beat_grid: no beat grid available — cuts unchanged")
    return None, "none"
