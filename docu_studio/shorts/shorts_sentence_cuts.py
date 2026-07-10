"""Sentence-scoped cut planning: ties together per-sentence time spans and
per-sentence footage pool sizes so every Segment's footage is guaranteed to
come from the sentence actually narrating during that segment's time window
— this is the fix for footage/narration mismatch (a clip fetched for one
sentence playing during a different sentence's narration).
"""
from __future__ import annotations

import logging

from docu_studio.shorts.shorts_cuts import MAX_SEGMENT_DURATION, MIN_SEGMENT_DURATION, Segment, plan_cuts_window

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


LOOP_REVISIT_DURATION_SECONDS = 1.75
_LOOP_REVISIT_MIN_TOTAL_DURATION = MIN_SEGMENT_DURATION * 3


def apply_loop_revisit(
    segments: list[Segment], total_duration: float, sentence_zero_pool_source: str,
) -> list[Segment]:
    """Reserve the final LOOP_REVISIT_DURATION_SECONDS as a segment that
    replays sentence 0's own footage (clip_index=0 into sentence 0's pool,
    sentence_index=0, pool_source=*sentence_zero_pool_source* so it's
    logged consistently with whatever pool sentence 0 itself actually
    resolved to). The reservation is carved from the tail of the LAST
    segment only (never a different sentence's segment), and only if doing
    so leaves that segment at least MIN_SEGMENT_DURATION long — otherwise
    the revisit is skipped entirely for this run (logged), never shrinking
    below the floor.
    """
    if total_duration <= _LOOP_REVISIT_MIN_TOTAL_DURATION or not segments:
        _log.info("apply_loop_revisit: total_duration=%.2f too short — skipping", total_duration)
        return segments

    last = segments[-1]
    new_last_duration = last.duration - LOOP_REVISIT_DURATION_SECONDS
    if new_last_duration < MIN_SEGMENT_DURATION:
        _log.info(
            "apply_loop_revisit: last segment (%.2fs) too short to carve a %.2fs "
            "revisit tail without dropping below the %.2fs floor — skipping",
            last.duration, LOOP_REVISIT_DURATION_SECONDS, MIN_SEGMENT_DURATION,
        )
        return segments

    shrunk_last = Segment(
        index=last.index, start=last.start, duration=new_last_duration,
        clip_index=last.clip_index, sentence_index=last.sentence_index, pool_source=last.pool_source,
    )
    revisit = Segment(
        index=last.index + 1, start=last.start + new_last_duration,
        duration=LOOP_REVISIT_DURATION_SECONDS, clip_index=0,
        sentence_index=0, pool_source=sentence_zero_pool_source, loop_revisit=True,
    )
    _log.info(
        "apply_loop_revisit: reserved final %.2fs from sentence %s's last segment for revisit",
        LOOP_REVISIT_DURATION_SECONDS, last.sentence_index,
    )
    return segments[:-1] + [shrunk_last, revisit]


PUNCH_CARD_DURATION_SECONDS = 1.0
_PUNCH_CARD_MIN_DURATION = 0.8
# The flicker-bug fix: the old global _insert_punch_card allowed a target's
# remaining duration to shrink to 0.3s, producing a sub-floor sliver of
# footage right next to the card's hard cuts. This reuses the same
# MIN_SEGMENT_DURATION floor used everywhere else instead.
_PUNCH_MIN_REMAINDER = MIN_SEGMENT_DURATION


def insert_punch_card_scoped(
    segments: list[Segment],
    punch: tuple[int, str],
    spans: list[tuple[float, float]],
) -> tuple[list[Segment], tuple[float, float] | None]:
    """Insert a punch-card Segment for sentence *punch[0]*, drawing its time
    allocation only from within that sentence's own span
    [span_start, span_end) — it may shrink or split that sentence's own
    segment(s), but can never reach into a neighboring sentence's segment.
    If the sentence's span is too short to fit both the card
    (PUNCH_CARD_DURATION_SECONDS, floored at _PUNCH_CARD_MIN_DURATION) and
    leave its target segment at least _PUNCH_MIN_REMAINDER long, the card
    is skipped for this run (logged) rather than shrinking below that floor
    or reaching outside the sentence's own span — this is what prevents a
    punch card from colliding with an adjacent sentence's footage cut into
    a rapid flicker.

    Returns (segments, (card_start, card_end)) on success, or (segments
    unchanged, None) if placement isn't possible.
    """
    sentence_index, punch_text = punch
    if sentence_index >= len(spans):
        return segments, None
    span_start, span_end = spans[sentence_index]

    candidates = [s for s in segments if not s.loop_revisit and s.sentence_index == sentence_index]
    if not candidates:
        _log.info(
            "Punch card: sentence %d has no segments of its own (empty span or pool) — skipping",
            sentence_index,
        )
        return segments, None

    target = min(candidates, key=lambda s: abs(s.start - span_start))

    card_duration = min(PUNCH_CARD_DURATION_SECONDS, target.duration - _PUNCH_MIN_REMAINDER)
    if card_duration < _PUNCH_CARD_MIN_DURATION:
        _log.info(
            "Punch card: sentence %d's target segment (%.2fs) too short to fit a card "
            "and keep the %.2fs minimum-duration floor — skipping",
            sentence_index, target.duration, _PUNCH_MIN_REMAINDER,
        )
        return segments, None

    steal_from_start = target.start > span_start + 1e-9
    if steal_from_start:
        card_start = target.start
        new_target = Segment(
            index=target.index, start=target.start + card_duration,
            duration=target.duration - card_duration, clip_index=target.clip_index,
            sentence_index=target.sentence_index, pool_source=target.pool_source,
        )
    else:
        card_start = target.start + target.duration - card_duration
        if card_start < span_start - 1e-9:
            _log.info(
                "Punch card: sentence %d span too short to place card without "
                "spilling outside its own span — skipping", sentence_index,
            )
            return segments, None
        new_target = Segment(
            index=target.index, start=target.start,
            duration=target.duration - card_duration, clip_index=target.clip_index,
            sentence_index=target.sentence_index, pool_source=target.pool_source,
        )

    card_segment = Segment(
        index=target.index, start=card_start, duration=card_duration,
        clip_index=0, is_punch=True, punch_text=punch_text, sentence_index=sentence_index,
    )

    new_segments: list[Segment] = []
    for s in segments:
        if s is target:
            if steal_from_start:
                new_segments.append(card_segment)
                new_segments.append(new_target)
            else:
                new_segments.append(new_target)
                new_segments.append(card_segment)
        else:
            new_segments.append(s)

    reindexed = [
        Segment(
            index=i, start=s.start, duration=s.duration, clip_index=s.clip_index,
            loop_revisit=s.loop_revisit, is_punch=s.is_punch, punch_text=s.punch_text,
            sentence_index=s.sentence_index, pool_source=s.pool_source,
        )
        for i, s in enumerate(new_segments)
    ]
    return reindexed, (card_start, card_start + card_duration)
