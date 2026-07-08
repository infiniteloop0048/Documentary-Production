"""3-tier resolver chain for word-level timing in shorts assembly.

Tier 1: native TTS timestamps, only if the configured TTS adapter exposes them.
Tier 2: Whisper-based forced alignment — scaffolded, not implemented yet.
Tier 3: estimated timing — words distributed across the measured audio duration,
weighted by word character length.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

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
