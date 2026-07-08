"""Pure segment/cut planning and vertical-crop strategy decisions for shorts assembly.

Kept dependency-free (no ffmpeg, no adapters) so it is trivially unit-testable and
reproducible via seed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

MIN_SEGMENT_DURATION = 2.0
MAX_SEGMENT_DURATION = 4.0
MIN_SEGMENT_DELTA = 0.5

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


def plan_cuts(total_duration: float, n_clips: int, seed: int) -> list[Segment]:
    """Return a reproducible list of Segments that fill exactly *total_duration* seconds.

    Segment lengths vary between MIN_SEGMENT_DURATION and MAX_SEGMENT_DURATION seconds,
    each differing from its predecessor by at least MIN_SEGMENT_DELTA seconds. The final
    segment is trimmed so the segments sum exactly to *total_duration* — it may fall
    outside the min/max/delta rules by design (it exists to land exactly on the end of
    the audio track). *n_clips* assigns a cycling clip_index to each segment.
    """
    if total_duration <= 0:
        raise ValueError("total_duration must be > 0")
    if n_clips <= 0:
        raise ValueError("n_clips must be > 0")

    rng = random.Random(seed)

    if total_duration <= MIN_SEGMENT_DURATION:
        return [Segment(index=0, start=0.0, duration=total_duration, clip_index=0)]

    durations: list[float] = []
    elapsed = 0.0
    prev: float | None = None
    while True:
        candidate = _next_duration(rng, prev)
        if elapsed + candidate >= total_duration - MIN_SEGMENT_DURATION:
            durations.append(total_duration - elapsed)
            break
        durations.append(candidate)
        elapsed += candidate
        prev = candidate

    segments: list[Segment] = []
    start = 0.0
    for i, dur in enumerate(durations):
        segments.append(Segment(index=i, start=start, duration=dur, clip_index=i % n_clips))
        start += dur
    return segments


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
