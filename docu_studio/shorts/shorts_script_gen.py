"""Dedicated script generation for Shorts/Reels: cold-open hook, TTS-safe output,
per-sentence visual search queries.

Reuses only LLMProvider's public methods (generate_script, break_into_scenes) —
no adapter files are edited. See the plan's Global Constraints for why
break_into_scenes is repurposed to obtain structured per-sentence JSON.
"""
from __future__ import annotations

import re

SHORTS_WPM = 170

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def target_word_count(duration_seconds: int) -> int:
    """Return the target word count for *duration_seconds* at shorts pace (170 WPM)."""
    return round(duration_seconds / 60 * SHORTS_WPM)


def split_sentences(text: str) -> list[str]:
    """Split *text* into sentences on '.', '!', '?' boundaries, collapsing whitespace."""
    normalized = " ".join(text.split())
    if not normalized:
        return []
    parts = _SENTENCE_SPLIT_RE.split(normalized)
    return [p.strip() for p in parts if p.strip()]
