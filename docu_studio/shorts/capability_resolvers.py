"""3-tier resolver chain for word-level timing in shorts assembly.

Tier 1: native TTS timestamps, only if the configured TTS adapter exposes them.
Tier 2: Whisper-based forced alignment — scaffolded, not implemented yet.
Tier 3: estimated timing — words distributed across the measured audio duration,
weighted by word character length.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float
    end: float


def estimate_word_timestamps(script_text: str, duration: float) -> list[WordTiming]:
    """Distribute the words of *script_text* across *duration* seconds, weighting
    each word's time span by its character length (Tier 3 — no audio analysis)."""
    words = script_text.split()
    if not words or duration <= 0:
        return []
    weights = [len(w) for w in words]
    total_weight = sum(weights)
    timestamps: list[WordTiming] = []
    cursor = 0.0
    for word, weight in zip(words, weights):
        span = duration * (weight / total_weight)
        timestamps.append(WordTiming(word=word, start=cursor, end=cursor + span))
        cursor += span
    return timestamps


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
    raise NotImplementedError(
        "Tier 2 (Whisper-based forced alignment) is not implemented yet — "
        "lands in a follow-up task."
    )


def get_word_timestamps(
    audio_path: str, script_text: str, tts_adapter: TTSProvider
) -> tuple[list[WordTiming], str]:
    """Return (timestamps, tier_used) for *script_text* aligned to *audio_path*."""
    tier1 = _tier1_native_timestamps(tts_adapter, script_text, audio_path)
    if tier1 is not None:
        _log.info("get_word_timestamps: using Tier 1 (native TTS timestamps)")
        return tier1, "tier1_native"

    try:
        return _tier2_whisper_alignment(audio_path, script_text), "tier2_whisper"
    except NotImplementedError:
        pass

    duration = FFmpegWrapper().get_duration(audio_path)
    _log.info("get_word_timestamps: using Tier 3 (estimated timing)")
    return estimate_word_timestamps(script_text, duration), "tier3_estimated"
