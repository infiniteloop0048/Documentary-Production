"""Sentence-scoped cut planning: ties together per-sentence time spans and
per-sentence footage pool sizes so every Segment's footage is guaranteed to
come from the sentence actually narrating during that segment's time window
— this is the fix for footage/narration mismatch (a clip fetched for one
sentence playing during a different sentence's narration).
"""
from __future__ import annotations

import logging

from docu_studio.shorts.shorts_cuts import MAX_SEGMENT_DURATION, Segment, plan_cuts_window

_log = logging.getLogger(__name__)

# A sentence span shorter than this gets one clip spanning the whole span
# instead of being split into micro-cuts — matches plan_cuts_window's own
# MAX_SEGMENT_DURATION, since anything under it already fits in one segment.
_MICRO_CUT_THRESHOLD_SECONDS = MAX_SEGMENT_DURATION


def plan_sentence_scoped_cuts(
    spans: list[tuple[float, float]],
    pool_sizes: list[int],
    pool_sources: list[str],
    seed: int,
    beat_grid: list[float] | None = None,
) -> list[Segment]:
    """Return a reproducible, globally-reindexed list of Segments where every
    segment's clip_index refers only to its OWN sentence's footage pool
    (never a neighboring sentence's) and stays entirely within that
    sentence's [start, end) span.

    *spans* and *pool_sizes*/*pool_sources* must be the same length, one
    entry per sentence (spans[i] from sentence_spans(), pool_sizes[i] the
    number of usable clips for sentence i's own segments — the caller is
    responsible for substituting the topic-level fallback pool's size when
    a sentence's own pool is empty, and recording that in pool_sources[i]
    as "fallback" instead of "sentence").

    A sentence's span shorter than _MICRO_CUT_THRESHOLD_SECONDS gets exactly
    one segment spanning the full span (clip_index=0 into that sentence's
    pool). A longer span is split via plan_cuts_window into 2+ micro-cuts
    that stay entirely inside the span; *beat_grid* is passed through
    unchanged (plan_cuts_window itself clamps it to the sentence's own
    window).
    """
    if len(spans) != len(pool_sizes) or len(spans) != len(pool_sources):
        raise ValueError("spans, pool_sizes, and pool_sources must be the same length")

    all_segments: list[Segment] = []
    for i, (span, n_clips, source) in enumerate(zip(spans, pool_sizes, pool_sources)):
        span_start, span_end = span
        duration = span_end - span_start
        if n_clips <= 0:
            raise ValueError(f"sentence {i}: pool_sizes must be > 0 (got {n_clips})")

        if duration <= 0:
            _log.info("plan_sentence_scoped_cuts: sentence %d span is zero-length — skipping", i)
            continue

        if duration < _MICRO_CUT_THRESHOLD_SECONDS:
            sentence_segments = [Segment(index=0, start=span_start, duration=duration, clip_index=0)]
        else:
            sentence_segments = plan_cuts_window(
                window_start=span_start, window_duration=duration,
                n_clips=n_clips, seed=seed + i, beat_grid=beat_grid,
            )

        for seg in sentence_segments:
            all_segments.append(Segment(
                index=len(all_segments), start=seg.start, duration=seg.duration,
                clip_index=seg.clip_index, sentence_index=i, pool_source=source,
            ))
        _log.info(
            "plan_sentence_scoped_cuts: sentence %d span=[%.2f,%.2f) -> %d segment(s), pool_source=%s",
            i, span_start, span_end, len(sentence_segments), source,
        )

    return all_segments
