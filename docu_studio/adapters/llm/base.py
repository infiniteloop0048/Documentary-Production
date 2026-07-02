"""LLMProvider ABC — all pipeline code imports only this interface."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable

# Single-call completions reliably undershoot a requested word count (models tend to
# stop well short of a target length even when max_tokens allows more), so long scripts
# must be generated in chunks with a running word-count check between calls.
_SCRIPT_CHUNK_TOLERANCE = 0.10

# Chunk budget scales with the target so long-form requests (45-120 min) get
# proportionally more attempts instead of hitting the same cap as a 30-min script.
# 1,200 words/chunk is a conservative estimate of realistic per-call output (observed
# chunk yields range ~1,000-1,800 words — see test_anthropic_adapter.py), plus a small
# buffer for the initial undershoot-and-catch-up pattern models exhibit.
_EXPECTED_WORDS_PER_CHUNK = 1200
_CHUNK_BUDGET_BUFFER = 2
_MIN_CHUNK_BUDGET = 2
_MAX_CHUNK_BUDGET = 20

# If a single chunk contributes less than this fraction of the target (or this many
# words, whichever is larger) while still short of target, the model has plateaued —
# further chunks are unlikely to help, so stop instead of burning the whole budget.
_DIMINISHING_RETURNS_RATIO = 0.05
_DIMINISHING_RETURNS_MIN_WORDS = 150


def _chunk_budget(target_words: int) -> int:
    """Return the max number of chunk-generation attempts for *target_words*."""
    estimated = math.ceil(target_words / _EXPECTED_WORDS_PER_CHUNK) + _CHUNK_BUDGET_BUFFER
    return max(_MIN_CHUNK_BUDGET, min(_MAX_CHUNK_BUDGET, estimated))


class LLMProvider(ABC):
    @abstractmethod
    def generate_script(
        self,
        topic: str,
        target_words: int,
        on_diminishing_returns: Callable[[int], None] | None = None,
    ) -> str:
        """Generate a documentary narration script for *topic* of approx *target_words* words.

        *on_diminishing_returns*, if given, is called with the remaining word shortfall
        if chunked generation stops early because a chunk's contribution plateaued.
        """

    @staticmethod
    def _generate_script_in_chunks(
        target_words: int,
        generate_chunk: Callable[[str, int], str],
        on_diminishing_returns: Callable[[int], None] | None = None,
    ) -> str:
        """Call *generate_chunk* repeatedly until *target_words* is reached (within tolerance).

        *generate_chunk(script_so_far, words_needed)* returns the text to append next.
        On the first call ``script_so_far`` is ``""`` (fresh script); on later calls it
        holds everything generated so far, so the callback can ask the model to continue
        from there instead of restarting. Stops after a target-sized chunk budget even
        if still short, so a model that won't converge can't loop forever. Also stops
        early — via *on_diminishing_returns* — if a chunk's contribution plateaus well
        below what's still needed, rather than exhausting the whole budget on a model
        that isn't making meaningful progress.
        """
        script = ""
        max_chunks = _chunk_budget(target_words)
        for _ in range(max_chunks):
            words_so_far = len(script.split())
            words_needed = target_words - words_so_far
            if script and words_needed <= target_words * _SCRIPT_CHUNK_TOLERANCE:
                break
            chunk = generate_chunk(script, words_needed).strip()
            if not chunk:
                break
            chunk_words = len(chunk.split())
            script = f"{script}\n\n{chunk}" if script else chunk

            shortfall = target_words - len(script.split())
            if shortfall <= target_words * _SCRIPT_CHUNK_TOLERANCE:
                continue  # close enough — the top-of-loop check ends things cleanly

            min_contribution = max(
                target_words * _DIMINISHING_RETURNS_RATIO, _DIMINISHING_RETURNS_MIN_WORDS
            )
            if chunk_words < min_contribution:
                if on_diminishing_returns is not None:
                    on_diminishing_returns(shortfall)
                break
        return script

    @abstractmethod
    def break_into_scenes(self, script: str) -> list[dict]:
        """Split *script* into a list of scene dicts with 'title' and 'narration' keys."""

    @abstractmethod
    def extract_visual_keywords(self, title: str, narration: str) -> list[str]:
        """Return stock-footage search keywords for a scene."""

    @abstractmethod
    def suggest_topic(self) -> str:
        """Suggest a trending documentary topic (fallback for topic discovery)."""
