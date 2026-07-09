"""Pure segment/cut planning and vertical-crop strategy decisions for shorts assembly.

Kept dependency-free (no ffmpeg, no adapters) so it is trivially unit-testable and
reproducible via seed.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass

_log = logging.getLogger(__name__)

MIN_SEGMENT_DURATION = 2.0
MAX_SEGMENT_DURATION = 4.0
MIN_SEGMENT_DELTA = 0.5

BEAT_SNAP_TOLERANCE = 0.4
LOOP_REVISIT_DURATION_SECONDS = 1.75
# Below this, reserving a ~1.75s revisit slot would eat too much of the plan
# (it would collide with or exceed the min single-segment fallback path).
_LOOP_REVISIT_MIN_TOTAL_DURATION = MIN_SEGMENT_DURATION * 3

# 16:9 is the baseline aspect ratio for ordinary stock footage — converting it to a
# 9:16 vertical frame via center-crop is the normal, expected technique (it always
# discards a large fraction of raw width, and that's fine). This threshold instead
# measures width discarded *beyond* what a 16:9 source would already need to shed, so
# only genuinely panoramic/ultra-wide sources (e.g. ~32:9) fall back to blur-pad.
_BASELINE_ASPECT = 16 / 9
CROP_DISCARD_THRESHOLD = 0.45


@dataclass(frozen=True)
class Segment:
    index: int
    start: float
    duration: float
    clip_index: int
    loop_revisit: bool = False
    is_punch: bool = False
    punch_text: str | None = None


def plan_cuts(
    total_duration: float,
    n_clips: int,
    seed: int,
    beat_grid: list[float] | None = None,
    loop_revisit: bool = False,
) -> list[Segment]:
    """Return a reproducible list of Segments that fill exactly *total_duration* seconds.

    Segment lengths vary between MIN_SEGMENT_DURATION and MAX_SEGMENT_DURATION seconds,
    each differing from its predecessor by at least MIN_SEGMENT_DELTA seconds. The final
    segment is trimmed so the segments sum exactly to *total_duration* — it may fall
    outside the min/max/delta rules by design (it exists to land exactly on the end of
    the audio track). *n_clips* assigns a cycling clip_index to each segment.

    *beat_grid*, if given, is a list of beat times (seconds); every interior cut
    boundary (not the very start or the very end) is snapped to the nearest beat
    within BEAT_SNAP_TOLERANCE seconds, never reusing a beat for two different
    cuts and never crossing a neighboring boundary. Total duration is always
    preserved exactly regardless of snapping.

    *loop_revisit*, if True and *total_duration* is long enough, reserves the
    final LOOP_REVISIT_DURATION_SECONDS as a Segment flagged loop_revisit=True
    with clip_index=0 (the first clip's source) — its cut point is included in
    beat snapping like any other interior boundary.
    """
    if total_duration <= 0:
        raise ValueError("total_duration must be > 0")
    if n_clips <= 0:
        raise ValueError("n_clips must be > 0")

    rng = random.Random(seed)

    revisit_duration = 0.0
    core_duration = total_duration
    if loop_revisit and total_duration > _LOOP_REVISIT_MIN_TOTAL_DURATION:
        revisit_duration = LOOP_REVISIT_DURATION_SECONDS
        core_duration = total_duration - revisit_duration

    if core_duration <= MIN_SEGMENT_DURATION:
        core_segments = [Segment(index=0, start=0.0, duration=core_duration, clip_index=0)]
    else:
        durations: list[float] = []
        elapsed = 0.0
        prev: float | None = None
        while True:
            candidate = _next_duration(rng, prev)
            if elapsed + candidate >= core_duration - MIN_SEGMENT_DURATION:
                durations.append(core_duration - elapsed)
                break
            durations.append(candidate)
            elapsed += candidate
            prev = candidate

        core_segments = []
        start = 0.0
        for i, dur in enumerate(durations):
            core_segments.append(Segment(index=i, start=start, duration=dur, clip_index=i % n_clips))
            start += dur

    boundaries = [0.0] + [s.start for s in core_segments[1:]] + [core_duration]
    if revisit_duration > 0:
        boundaries.append(total_duration)

    # Indices of boundaries actually moved by beat snapping. Only segments adjacent to a
    # moved boundary need their duration recomputed from the (post-snap) boundary
    # difference — everything else keeps its originally-computed duration bit-for-bit,
    # since `(a + b) - a` is not guaranteed to equal `b` exactly in IEEE-754. This keeps
    # the default (no beat_grid, no loop_revisit) path byte-identical to the pre-existing
    # implementation, where durations were never reconstructed via boundary subtraction.
    snapped_indices: set[int] = set()
    if beat_grid:
        original_boundaries = list(boundaries)
        boundaries, snapped_count = _snap_boundaries_to_beats(boundaries, beat_grid)
        snapped_indices = {
            i for i, (orig, new) in enumerate(zip(original_boundaries, boundaries))
            if orig != new
        }
        total_interior = max(0, len(boundaries) - 2)
        _log.info(
            "plan_cuts: beat snap — %d/%d interior cuts snapped, %d stayed",
            snapped_count, total_interior, total_interior - snapped_count,
        )

    segments: list[Segment] = []
    n_segments = len(boundaries) - 1
    for i in range(n_segments):
        is_revisit = revisit_duration > 0 and i == n_segments - 1
        if i in snapped_indices or (i + 1) in snapped_indices:
            seg_duration = boundaries[i + 1] - boundaries[i]
        elif is_revisit:
            seg_duration = revisit_duration
        else:
            seg_duration = core_segments[i].duration
        segments.append(Segment(
            index=i,
            start=boundaries[i],
            duration=seg_duration,
            clip_index=0 if is_revisit else i % n_clips,
            loop_revisit=is_revisit,
        ))
    return segments


def _snap_boundaries_to_beats(
    boundaries: list[float], beat_grid: list[float]
) -> tuple[list[float], int]:
    """Snap interior boundaries (all but the first and last) to the nearest
    beat within BEAT_SNAP_TOLERANCE seconds. Never reuses a beat for two
    different cuts, and never crosses a neighboring (already-placed)
    boundary. Returns (new_boundaries, count_snapped)."""
    result = list(boundaries)
    used_beats: set[float] = set()
    snapped = 0
    for i in range(1, len(result) - 1):
        prev_b = result[i - 1]
        next_b = boundaries[i + 1]
        target = result[i]
        candidates = [
            b for b in beat_grid
            if abs(b - target) <= BEAT_SNAP_TOLERANCE
            and b not in used_beats
            and prev_b < b < next_b
        ]
        if candidates:
            nearest = min(candidates, key=lambda b: abs(b - target))
            result[i] = nearest
            used_beats.add(nearest)
            snapped += 1
    return result, snapped


def _next_duration(rng: random.Random, prev: float | None) -> float:
    for _ in range(50):
        candidate = round(rng.uniform(MIN_SEGMENT_DURATION, MAX_SEGMENT_DURATION), 2)
        if prev is None or abs(candidate - prev) >= MIN_SEGMENT_DELTA:
            return candidate
    midpoint = (MIN_SEGMENT_DURATION + MAX_SEGMENT_DURATION) / 2
    return MIN_SEGMENT_DURATION if (prev or 0) > midpoint else MAX_SEGMENT_DURATION


def choose_crop_strategy(source_width: int, source_height: int) -> str:
    """Return 'center_crop' or 'blur_pad' for converting a source clip to vertical.

    'center_crop' scales the source to fill the vertical frame and crops the excess
    width — the normal technique, fine for anything up to and including 16:9. Sources
    wider than that switch to 'blur_pad' once the *additional* width they'd lose beyond
    a 16:9 source's own crop exceeds CROP_DISCARD_THRESHOLD.
    """
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source_width and source_height must be > 0")
    source_aspect = source_width / source_height
    if source_aspect <= _BASELINE_ASPECT:
        return "center_crop"
    excess_width_fraction = 1 - (_BASELINE_ASPECT / source_aspect)
    return "blur_pad" if excess_width_fraction > CROP_DISCARD_THRESHOLD else "center_crop"
