# Shorts / Reels Generation Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Short / Reel" generation mode to Docu Studio — a new, parallel vertical (1080×1920) short-form video pipeline (15–60s) that lives entirely in a new `docu_studio/shorts/` package, reuses existing LLM/TTS/footage adapters and `FFmpegWrapper` without editing them, and leaves the existing documentary flow byte-for-byte unchanged.

**Architecture:** A `ShortsRunner` (mirrors `PipelineRunner`) orchestrates: (1) a dedicated hook/escalation/payoff script prompt with TTS-safe output and per-sentence visual queries (`shorts_script_gen.py`), (2) audio-first assembly — TTS first, then footage fetch/window/vertical-convert/Ken-Burns/concat/mux keyed off the *measured* audio duration (`shorts_assembly.py`, `shorts_cuts.py`, `shorts_ffmpeg.py`), and (3) a 3-tier word-timing resolver scaffold (`capability_resolvers.py`). The GUI gets a third mode card and a duration-slider config screen wired through a new `Bridge.start_shorts_run()` that is fully additive — `Bridge.start_run()` (documentary path) is not modified.

**Tech Stack:** Python 3.11+, existing `docu_studio.adapters.{llm,tts,footage}` interfaces, `docu_studio.media.ffmpeg_wrapper.FFmpegWrapper` (subclassed, not edited), pywebview/HTML/JS frontend, pytest.

## Global Constraints

- Use `.venv/bin/python` for everything (never `venv/`). Run app via `DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Do NOT modify `docu_studio/pipeline/`, `docu_studio/pipeline/runner.py`, `docu_studio/adapters/**` (existing files), `docu_studio/history/`, `docu_studio/licensing.py`, or any existing test file. New adapter-level helpers must go in new files only (none are needed in this plan — everything reuses existing adapter public interfaces).
- The existing documentary flow (`RunMode.GUIDED` / `RunMode.FULL_AUTO`, `Bridge.start_run`, `PipelineRunner`) must remain byte-for-byte unchanged in behavior. All shorts logic is additive: new files, or new methods/branches appended to existing GUI files without touching existing code paths.
- `docu_studio/gui/app.py`, `gui/screens/`, `gui/widgets/`, `gui/theme.py`, `gui/tokens.py` are dead CustomTkinter code — never touch them.
- `FFmpegWrapper` (`docu_studio/media/ffmpeg_wrapper.py`) is never edited. All shorts-only ffmpeg operations go in a new subclass `ShortsFFmpeg` in `docu_studio/shorts/shorts_ffmpeg.py`, reusing inherited `get_duration()`, `trim_clip()`, `_check()`, `self._ffmpeg`/`self._ffprobe`, and the explicit `-map` audio-from-TTS-only discipline established in `mux_audio_video()`.
- Bump the `?v=N` cache buster in `docu_studio/gui/webview_app.py` (currently `?v=7` → `?v=8`) after any HTML/JS edit.
- Full suite via `.venv/bin/python -m pytest`. Accepted baseline (confirmed before this work): **24 failed, 150 passed, 1 collection error** (`tests/integration/test_edge_tts_adapter.py` — missing `edge_tts_adapter` module, pre-existing). Zero NEW failures after this plan.
- No adapter (gtts, elevenlabs, deepgram) currently exposes word-level timestamps — confirmed by reading all three TTS adapter files. Tier 1 of the capability resolver is therefore a scaffold that will not fire yet; this is expected and matches the spec ("Tier 1 ... IF the current TTS adapter exposes them").
- `LLMProvider`'s only public methods are `generate_script(topic, target_words, on_diminishing_returns=None) -> str`, `break_into_scenes(script) -> list[dict]`, `extract_visual_keywords(title, narration) -> list[str]`, `suggest_topic() -> str`. There is no raw/structured-JSON passthrough. To get genuine LLM-returned structured JSON (per-sentence visual queries) without editing any adapter, this plan reuses `break_into_scenes()` — the only method whose adapters already parse JSON/tool-use output into `list[dict]` with built-in retry — by feeding it the generated shorts script plus an override instruction that asks it to return one `{title, narration}` entry per sentence (`title` repurposed as the visual query). This is a deliberate, documented reuse of an existing method's JSON-parsing machinery, not new adapter code.

---

### Task 1: `ShortsConfig` dataclass and constants

**Files:**
- Create: `docu_studio/shorts/__init__.py`
- Create: `docu_studio/shorts/shorts_config.py`
- Test: `tests/unit/test_shorts_config.py`

**Interfaces:**
- Produces: `ShortsConfig(topic: str, duration_seconds: int = 30)` — raises `ValueError` outside `[15, 60]`. Constants: `SHORTS_WIDTH=1080`, `SHORTS_HEIGHT=1920`, `SHORTS_MIN_DURATION=15`, `SHORTS_MAX_DURATION=60`, `SHORTS_DEFAULT_DURATION=30`, `SHORTS_WPM=170`.

- [ ] **Step 1: Create the package `__init__.py`**

```python
"""Shorts / Reels generation — a parallel assembly path to the documentary pipeline.

Reuses docu_studio.adapters.{llm,tts,footage} and docu_studio.media.ffmpeg_wrapper
via their existing public interfaces only; none of those files are edited here.
"""
```

- [ ] **Step 2: Write the failing test**

```python
"""Unit tests for ShortsConfig bounds validation."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_config import (
    SHORTS_DEFAULT_DURATION,
    SHORTS_HEIGHT,
    SHORTS_MAX_DURATION,
    SHORTS_MIN_DURATION,
    SHORTS_WIDTH,
    ShortsConfig,
)


class TestShortsConfig:
    def test_default_construction_is_valid(self) -> None:
        cfg = ShortsConfig(topic="Ocean facts")
        assert cfg.topic == "Ocean facts"
        assert cfg.duration_seconds == SHORTS_DEFAULT_DURATION

    def test_accepts_min_and_max_bounds(self) -> None:
        ShortsConfig(topic="x", duration_seconds=SHORTS_MIN_DURATION)
        ShortsConfig(topic="x", duration_seconds=SHORTS_MAX_DURATION)

    def test_rejects_below_minimum(self) -> None:
        with pytest.raises(ValueError):
            ShortsConfig(topic="x", duration_seconds=SHORTS_MIN_DURATION - 1)

    def test_rejects_above_maximum(self) -> None:
        with pytest.raises(ValueError):
            ShortsConfig(topic="x", duration_seconds=SHORTS_MAX_DURATION + 1)

    def test_aspect_constants_are_vertical(self) -> None:
        assert SHORTS_WIDTH == 1080
        assert SHORTS_HEIGHT == 1920
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.shorts.shorts_config'`

- [ ] **Step 4: Write the implementation**

```python
"""Configuration for a single Shorts/Reels generation run."""
from __future__ import annotations

from dataclasses import dataclass

SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_MIN_DURATION = 15
SHORTS_MAX_DURATION = 60
SHORTS_DEFAULT_DURATION = 30
SHORTS_WPM = 170


@dataclass
class ShortsConfig:
    topic: str
    duration_seconds: int = SHORTS_DEFAULT_DURATION

    def __post_init__(self) -> None:
        if not (SHORTS_MIN_DURATION <= self.duration_seconds <= SHORTS_MAX_DURATION):
            raise ValueError(
                f"duration_seconds must be between {SHORTS_MIN_DURATION} and "
                f"{SHORTS_MAX_DURATION}, got {self.duration_seconds}"
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_config.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add docu_studio/shorts/__init__.py docu_studio/shorts/shorts_config.py tests/unit/test_shorts_config.py
git commit -m "feat(shorts): add ShortsConfig dataclass and constants"
```

---

### Task 2: `plan_cuts` — pure, seeded cut-plan generator

**Files:**
- Create: `docu_studio/shorts/shorts_cuts.py`
- Test: `tests/unit/test_shorts_cuts.py`

**Interfaces:**
- Consumes: nothing from other shorts modules.
- Produces: `Segment(index: int, start: float, duration: float, clip_index: int)` (frozen dataclass), `plan_cuts(total_duration: float, n_clips: int, seed: int) -> list[Segment]`, constants `MIN_SEGMENT_DURATION=2.0`, `MAX_SEGMENT_DURATION=4.0`, `MIN_SEGMENT_DELTA=0.5`. Later tasks import `Segment` and `plan_cuts` from here.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for plan_cuts — pure, seeded segment timing for shorts assembly."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_cuts import (
    MAX_SEGMENT_DURATION,
    MIN_SEGMENT_DELTA,
    MIN_SEGMENT_DURATION,
    plan_cuts,
)


class TestPlanCuts:
    def test_segments_sum_to_exact_total_duration(self) -> None:
        segments = plan_cuts(total_duration=30.0, n_clips=8, seed=1)
        assert sum(s.duration for s in segments) == pytest.approx(30.0, abs=0.02)

    def test_last_segment_lands_exactly_on_audio_end(self) -> None:
        segments = plan_cuts(total_duration=47.3, n_clips=10, seed=7)
        assert segments[-1].start + segments[-1].duration == pytest.approx(47.3, abs=0.02)

    def test_non_final_segments_respect_min_max_bounds(self) -> None:
        segments = plan_cuts(total_duration=60.0, n_clips=15, seed=42)
        for seg in segments[:-1]:
            assert MIN_SEGMENT_DURATION <= seg.duration <= MAX_SEGMENT_DURATION

    def test_lengths_are_varied_not_uniform(self) -> None:
        segments = plan_cuts(total_duration=45.0, n_clips=12, seed=3)
        durations = [s.duration for s in segments]
        assert len(set(durations)) > 1

    def test_neighbors_differ_by_at_least_min_delta(self) -> None:
        segments = plan_cuts(total_duration=45.0, n_clips=12, seed=3)
        # exclude the pair ending at the trimmed final segment
        for a, b in zip(segments[:-2], segments[1:-1]):
            assert abs(b.duration - a.duration) >= MIN_SEGMENT_DELTA - 1e-9

    def test_same_seed_is_reproducible(self) -> None:
        a = plan_cuts(total_duration=33.0, n_clips=9, seed=99)
        b = plan_cuts(total_duration=33.0, n_clips=9, seed=99)
        assert a == b

    def test_different_seed_changes_the_plan(self) -> None:
        a = plan_cuts(total_duration=33.0, n_clips=9, seed=1)
        b = plan_cuts(total_duration=33.0, n_clips=9, seed=2)
        assert a != b

    def test_clip_index_cycles_within_n_clips(self) -> None:
        segments = plan_cuts(total_duration=60.0, n_clips=3, seed=5)
        assert all(0 <= s.clip_index < 3 for s in segments)

    def test_short_total_duration_returns_single_trimmed_segment(self) -> None:
        segments = plan_cuts(total_duration=1.5, n_clips=1, seed=1)
        assert len(segments) == 1
        assert segments[0].duration == pytest.approx(1.5)

    def test_rejects_non_positive_total_duration(self) -> None:
        with pytest.raises(ValueError):
            plan_cuts(total_duration=0.0, n_clips=1, seed=1)

    def test_rejects_non_positive_n_clips(self) -> None:
        with pytest.raises(ValueError):
            plan_cuts(total_duration=10.0, n_clips=0, seed=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_cuts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.shorts.shorts_cuts'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_cuts.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/shorts_cuts.py tests/unit/test_shorts_cuts.py
git commit -m "feat(shorts): add plan_cuts pure segment planner"
```

---

### Task 3: `choose_crop_strategy` tests

**Files:**
- Modify: `tests/unit/test_shorts_cuts.py` (append a new test class — `choose_crop_strategy` was implemented in Task 2 alongside `plan_cuts` since both live in `shorts_cuts.py`; this task adds its dedicated test coverage)

**Interfaces:**
- Consumes: `choose_crop_strategy` from Task 2.

- [ ] **Step 1: Write the failing tests (append to the same file)**

```python
from docu_studio.shorts.shorts_cuts import choose_crop_strategy


class TestChooseCropStrategy:
    def test_standard_16_9_uses_center_crop(self) -> None:
        assert choose_crop_strategy(1920, 1080) == "center_crop"

    def test_already_vertical_source_uses_center_crop(self) -> None:
        assert choose_crop_strategy(1080, 1920) == "center_crop"

    def test_square_source_uses_center_crop(self) -> None:
        assert choose_crop_strategy(1080, 1080) == "center_crop"

    def test_moderately_wide_21_9_uses_center_crop(self) -> None:
        assert choose_crop_strategy(2560, 1080) == "center_crop"

    def test_ultra_wide_32_9_uses_blur_pad(self) -> None:
        assert choose_crop_strategy(3840, 1080) == "blur_pad"

    def test_rejects_non_positive_dimensions(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            choose_crop_strategy(0, 1080)
        with pytest.raises(ValueError):
            choose_crop_strategy(1920, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_cuts.py::TestChooseCropStrategy -v`
Expected: FAIL — `TestChooseCropStrategy` doesn't exist yet (this collects as an error/failure since the class is new; if `choose_crop_strategy` from Task 2 already exists and passes trivially, treat this step as confirming the tests execute against the already-implemented function — record actual PASS/FAIL here before Step 3).

- [ ] **Step 3: Verify implementation from Task 2 satisfies the new tests**

`choose_crop_strategy` was already implemented in Task 2's `shorts_cuts.py`. Run:

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_cuts.py -v`
Expected: PASS (17 tests total — 11 from Task 2 + 6 new)

If any fail, fix `choose_crop_strategy` in `docu_studio/shorts/shorts_cuts.py` (not the test) until they pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_shorts_cuts.py
git commit -m "test(shorts): add choose_crop_strategy coverage"
```

---

### Task 4: Tier 3 estimated word timestamps

**Files:**
- Create: `docu_studio/shorts/capability_resolvers.py`
- Test: `tests/unit/test_shorts_capability_resolvers.py`

**Interfaces:**
- Produces: `WordTiming(word: str, start: float, end: float)` (frozen dataclass), `estimate_word_timestamps(script_text: str, duration: float) -> list[WordTiming]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the Tier-3 estimated word-timing algorithm."""
from __future__ import annotations

import pytest

from docu_studio.shorts.capability_resolvers import WordTiming, estimate_word_timestamps


class TestEstimateWordTimestamps:
    def test_empty_script_returns_empty(self) -> None:
        assert estimate_word_timestamps("", 10.0) == []

    def test_zero_duration_returns_empty(self) -> None:
        assert estimate_word_timestamps("hello world", 0.0) == []

    def test_timestamps_span_the_full_duration(self) -> None:
        timestamps = estimate_word_timestamps("one two three four five", 10.0)
        assert timestamps[0].start == pytest.approx(0.0)
        assert timestamps[-1].end == pytest.approx(10.0, abs=1e-6)

    def test_timestamps_are_monotonically_increasing(self) -> None:
        timestamps = estimate_word_timestamps(
            "a short burst of narration with several words in it", 8.0
        )
        for a, b in zip(timestamps, timestamps[1:]):
            assert a.end == pytest.approx(b.start, abs=1e-9)
            assert b.start >= a.start

    def test_longer_words_get_more_time(self) -> None:
        timestamps = estimate_word_timestamps("a extraordinarily", 3.0)
        short_span = timestamps[0].end - timestamps[0].start
        long_span = timestamps[1].end - timestamps[1].start
        assert long_span > short_span

    def test_word_field_matches_input_order(self) -> None:
        timestamps = estimate_word_timestamps("red green blue", 3.0)
        assert [t.word for t in timestamps] == ["red", "green", "blue"]

    def test_returns_word_timing_instances(self) -> None:
        timestamps = estimate_word_timestamps("hi", 1.0)
        assert isinstance(timestamps[0], WordTiming)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_capability_resolvers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.shorts.capability_resolvers'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_capability_resolvers.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/capability_resolvers.py tests/unit/test_shorts_capability_resolvers.py
git commit -m "feat(shorts): add Tier-3 estimated word timestamps"
```

---

### Task 5: 3-tier `get_word_timestamps` chain

**Files:**
- Modify: `docu_studio/shorts/capability_resolvers.py` (append to the file created in Task 4)
- Modify: `tests/unit/test_shorts_capability_resolvers.py` (append tests)

**Interfaces:**
- Consumes: `WordTiming`, `estimate_word_timestamps` (Task 4); `docu_studio.adapters.tts.base.TTSProvider`; `docu_studio.media.ffmpeg_wrapper.FFmpegWrapper.get_duration(path: str) -> float` (existing, read-only reuse).
- Produces: `get_word_timestamps(audio_path: str, script_text: str, tts_adapter: TTSProvider) -> tuple[list[WordTiming], str]` — `tier_used` is one of `"tier1_native"`, `"tier3_estimated"` (`"tier2_whisper"` is unreachable until Tier 2 is implemented, since it always raises `NotImplementedError`).

- [ ] **Step 1: Write the failing tests (append to the test file)**

```python
from unittest.mock import MagicMock, patch

from docu_studio.shorts.capability_resolvers import get_word_timestamps


class TestGetWordTimestamps:
    def test_falls_back_to_tier3_when_adapter_has_no_native_timestamps(self) -> None:
        tts = MagicMock(spec=["synthesize"])  # no get_word_timestamps attribute
        with patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 5.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hello world", tts)
        assert tier == "tier3_estimated"
        assert timestamps[-1].end == 5.0

    def test_uses_tier1_when_adapter_exposes_native_timestamps(self) -> None:
        tts = MagicMock()
        tts.get_word_timestamps.return_value = [("hi", 0.0, 0.5), ("there", 0.5, 1.0)]
        timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier1_native"
        assert [t.word for t in timestamps] == ["hi", "there"]

    def test_tier1_exception_falls_back_to_tier3(self) -> None:
        tts = MagicMock()
        tts.get_word_timestamps.side_effect = RuntimeError("boom")
        with patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 2.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier3_estimated"

    def test_tier1_empty_result_falls_back_to_tier3(self) -> None:
        tts = MagicMock()
        tts.get_word_timestamps.return_value = []
        with patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 3.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier3_estimated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_capability_resolvers.py::TestGetWordTimestamps -v`
Expected: FAIL with `ImportError: cannot import name 'get_word_timestamps'`

- [ ] **Step 3: Append the implementation**

Append to `docu_studio/shorts/capability_resolvers.py`:

```python
from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_capability_resolvers.py -v`
Expected: PASS (11 tests total)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/capability_resolvers.py tests/unit/test_shorts_capability_resolvers.py
git commit -m "feat(shorts): add 3-tier get_word_timestamps resolver chain"
```

---

### Task 6: Shorts word-target math and sentence splitting

**Files:**
- Create: `docu_studio/shorts/shorts_script_gen.py`
- Test: `tests/unit/test_shorts_script_gen.py`

**Interfaces:**
- Produces: `SHORTS_WPM = 170` (re-exported for convenience), `target_word_count(duration_seconds: int) -> int`, `split_sentences(text: str) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for shorts script-generation helpers: word-target math and
sentence splitting."""
from __future__ import annotations

from docu_studio.shorts.shorts_script_gen import split_sentences, target_word_count


class TestTargetWordCount:
    def test_thirty_seconds_at_170_wpm(self) -> None:
        assert target_word_count(30) == round(30 / 60 * 170)  # 85

    def test_fifteen_seconds_minimum(self) -> None:
        assert target_word_count(15) == round(15 / 60 * 170)  # 42 or 43

    def test_sixty_seconds_maximum(self) -> None:
        assert target_word_count(60) == 170

    def test_scales_linearly_with_duration(self) -> None:
        assert target_word_count(60) == target_word_count(30) * 2 or \
            abs(target_word_count(60) - target_word_count(30) * 2) <= 1


class TestSplitSentences:
    def test_splits_on_terminal_punctuation(self) -> None:
        text = "This is one. This is two! Is this three?"
        assert split_sentences(text) == [
            "This is one.", "This is two!", "Is this three?",
        ]

    def test_collapses_internal_whitespace(self) -> None:
        text = "Hello   world.\nSecond   line."
        result = split_sentences(text)
        assert result == ["Hello world.", "Second line."]

    def test_empty_text_returns_empty_list(self) -> None:
        assert split_sentences("") == []
        assert split_sentences("   ") == []

    def test_single_sentence_no_trailing_punctuation(self) -> None:
        assert split_sentences("just one clause") == ["just one clause"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_script_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.shorts.shorts_script_gen'`

- [ ] **Step 3: Write the implementation (first half of the file)**

```python
"""Dedicated script generation for Shorts/Reels: cold-open hook, TTS-safe output,
per-sentence visual search queries.

Reuses only LLMProvider's public methods (generate_script, break_into_scenes) —
no adapter files are edited. See the plan's Global Constraints for why
break_into_scenes is repurposed to obtain structured per-sentence JSON.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from docu_studio.adapters.llm.base import LLMProvider

_log = logging.getLogger(__name__)

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_script_gen.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/shorts_script_gen.py tests/unit/test_shorts_script_gen.py
git commit -m "feat(shorts): add shorts word-target math and sentence splitting"
```

---

### Task 7: `generate_shorts_script` — LLM orchestration with defensive JSON fallback

**Files:**
- Modify: `docu_studio/shorts/shorts_script_gen.py` (append)
- Modify: `tests/unit/test_shorts_script_gen.py` (append)

**Interfaces:**
- Consumes: `target_word_count`, `split_sentences` (Task 6); `LLMProvider.generate_script(topic, target_words, on_diminishing_returns=None) -> str` and `LLMProvider.break_into_scenes(script) -> list[dict]` (existing, unedited).
- Produces: `ShortsScript(text: str, sentences: list[str], visual_queries: list[str])` (frozen dataclass, `len(visual_queries) == len(sentences)` always), `generate_shorts_script(topic: str, duration_seconds: int, llm: LLMProvider) -> ShortsScript`. Later tasks (`shorts_assembly.py`, `shorts_runner.py`) consume `ShortsScript`.

- [ ] **Step 1: Write the failing tests (append to the test file)**

```python
from unittest.mock import MagicMock

from docu_studio.shorts.shorts_script_gen import ShortsScript, generate_shorts_script


class TestGenerateShortsScript:
    def test_happy_path_returns_aligned_queries(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger. Loop back now."
        llm.break_into_scenes.return_value = [
            {"title": "aerial city night", "narration": "Fact one is huge."},
            {"title": "close-up hands typing", "narration": "Fact two is bigger."},
            {"title": "sunrise timelapse", "narration": "Loop back now."},
        ]

        result = generate_shorts_script("Cities at night", 30, llm)

        assert isinstance(result, ShortsScript)
        assert result.sentences == [
            "Fact one is huge.", "Fact two is bigger.", "Loop back now.",
        ]
        assert result.visual_queries == [
            "aerial city night", "close-up hands typing", "sunrise timelapse",
        ]
        assert len(result.visual_queries) == len(result.sentences)

    def test_malformed_json_response_retries_once_then_falls_back_to_topic(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        # First call: wrong count (parse/shape mismatch). Second call: still wrong.
        llm.break_into_scenes.side_effect = [
            [{"title": "only one", "narration": "One sentence."}],  # count mismatch
            RuntimeError("model returned invalid JSON"),             # exception
        ]

        result = generate_shorts_script("Space facts", 30, llm)

        assert result.sentences == ["One sentence.", "Two sentence."]
        assert result.visual_queries == ["Space facts", "Space facts"]
        assert llm.break_into_scenes.call_count == 2

    def test_uses_generate_script_with_target_word_count(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Just one sentence here."
        llm.break_into_scenes.return_value = [
            {"title": "topic shot", "narration": "Just one sentence here."},
        ]

        generate_shorts_script("Ocean depths", 15, llm)

        args, kwargs = llm.generate_script.call_args
        # target_words is the 2nd positional/keyword arg to generate_script
        assert kwargs.get("target_words", args[1] if len(args) > 1 else None) == round(15 / 60 * 170)

    def test_empty_script_returns_no_sentences_no_queries(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = ""
        result = generate_shorts_script("Nothing", 30, llm)
        assert result.sentences == []
        assert result.visual_queries == []
        llm.break_into_scenes.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_script_gen.py::TestGenerateShortsScript -v`
Expected: FAIL with `ImportError: cannot import name 'generate_shorts_script'`

- [ ] **Step 3: Append the implementation**

Append to `docu_studio/shorts/shorts_script_gen.py`:

```python
_SCRIPT_INSTRUCTIONS_TEMPLATE = (
    "You are writing narration for a short-form vertical video (like a YouTube Short "
    "or Instagram Reel) about: {topic}\n\n"
    "STRUCTURE (mandatory):\n"
    "1. Cold-open hook as the very first sentence — a surprising statistic, a "
    "provocative question, or a bold claim. NEVER start with phrases like "
    "'In this video' or 'Today we're going to talk about'.\n"
    "2. Then 2-3 rapid, escalating facts that build on each other.\n"
    "3. A payoff last line that loops back to the hook.\n\n"
    "OUTPUT FORMAT (mandatory):\n"
    "- Plain spoken text only. No markdown, no asterisks, no headers, no bullet "
    "points, no emojis, no quotation marks around the whole thing.\n"
    "- Write numbers the way they should be SPOKEN, e.g. 'ninety percent' not '90%', "
    "'three point five million' not '3.5 million'.\n"
    "- Short sentences. Use punctuation for spoken pacing.\n"
    "- Target length: approximately {target_words} words.\n\n"
    "Write only the narration text — nothing else."
)

_QUERY_OVERRIDE_TEMPLATE = (
    "{script}\n\n"
    "---\n"
    "IGNORE the 'logical scenes' framing in the instructions above. Instead, split "
    "the script above into its individual sentences, in the exact order they appear, "
    "with no merging, omission, or paraphrasing. For each sentence:\n"
    "- 'narration' must be the sentence exactly as written above.\n"
    "- 'title' must be a concrete 2-5 word visual search query describing stock "
    "footage that would visually match that sentence (e.g. 'aerial city night', "
    "'close-up hands typing'). No abstract or vague terms.\n"
    "Return one entry per sentence, in order."
)


@dataclass(frozen=True)
class ShortsScript:
    text: str
    sentences: list[str]
    visual_queries: list[str]


def _fallback_queries(topic: str, count: int) -> list[str]:
    return [topic] * count


def _extract_queries_via_llm(
    llm: LLMProvider, script: str, sentence_count: int
) -> list[str] | None:
    """Ask the LLM (via break_into_scenes, repurposed for structured JSON output) for
    a per-sentence visual query. Returns a list aligned to *sentence_count*, or None
    if the response could not be parsed into exactly that many entries."""
    try:
        raw = llm.break_into_scenes(_QUERY_OVERRIDE_TEMPLATE.format(script=script))
    except Exception as exc:
        _log.warning("Shorts visual-query extraction call failed: %s", exc)
        return None
    queries = [str(item.get("title", "")).strip() for item in raw if isinstance(item, dict)]
    queries = [q for q in queries if q]
    if len(queries) != sentence_count:
        _log.warning(
            "Shorts visual-query extraction count mismatch: got %d, expected %d",
            len(queries), sentence_count,
        )
        return None
    return queries


def generate_shorts_script(topic: str, duration_seconds: int, llm: LLMProvider) -> ShortsScript:
    """Generate a TTS-safe shorts script and per-sentence visual queries for *topic*."""
    target_words = target_word_count(duration_seconds)
    prompt = _SCRIPT_INSTRUCTIONS_TEMPLATE.format(topic=topic, target_words=target_words)
    text = llm.generate_script(topic=prompt, target_words=target_words).strip()

    sentences = split_sentences(text)
    if not sentences:
        return ShortsScript(text=text, sentences=[], visual_queries=[])

    queries = _extract_queries_via_llm(llm, text, len(sentences))
    if queries is None:
        _log.info("Shorts visual-query extraction failed, retrying once")
        queries = _extract_queries_via_llm(llm, text, len(sentences))
    if queries is None:
        _log.warning(
            "Shorts visual-query extraction failed twice, falling back to topic-level query"
        )
        queries = _fallback_queries(topic, len(sentences))

    return ShortsScript(text=text, sentences=sentences, visual_queries=queries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_script_gen.py -v`
Expected: PASS (12 tests total)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/shorts_script_gen.py tests/unit/test_shorts_script_gen.py
git commit -m "feat(shorts): add generate_shorts_script with defensive query fallback"
```

---

### Task 8: `ShortsFFmpeg` — shorts-only ffmpeg operations

**Files:**
- Create: `docu_studio/shorts/shorts_ffmpeg.py`

**Interfaces:**
- Consumes: `docu_studio.media.ffmpeg_wrapper.FFmpegWrapper` (inherits `self._ffmpeg`, `self._ffprobe`, `self._check`, `get_duration()`, `trim_clip()`, `has_audio_stream()` — none edited).
- Produces: `ShortsFFmpeg(FFmpegWrapper)` with `detect_motion_window(clip_path, clip_duration, window) -> tuple[float, str]`, `vertical_convert(input_path, output_path, strategy) -> None`, `apply_ken_burns(input_path, output_path, duration, direction, pan) -> None`, `concat_segments_video_only(input_paths, output_path) -> None`, `mux_shorts_audio(video_path, audio_path, output_path) -> None`. Consumed by Task 9 (`shorts_assembly.py`).

No dedicated pytest coverage in this task (ffmpeg subprocess behavior is exercised via the manual dry-run in Task 12, matching the existing codebase's pattern where `FFmpegWrapper` subprocess calls are covered by `tests/unit/test_ffmpeg_wrapper.py` using real ffmpeg binaries — this plan's mandated test list, per the spec, covers only `plan_cuts`, Tier-3 timing, crop-strategy, word-target math, and query-JSON parsing).

- [ ] **Step 1: Write the implementation**

```python
"""FFmpeg operations specific to Shorts/Reels assembly.

Subclasses FFmpegWrapper to reuse its ffmpeg/ffprobe binary resolution and the
_check() error-raising helper — the base class is never edited, only extended.
"""
from __future__ import annotations

import logging
import re
import subprocess

from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_log = logging.getLogger(__name__)

_MOTION_SAMPLE_WIDTH = 160
_MOTION_DETECT_TIMEOUT = 10.0
# 40% into the clip — inside the spec's required 20-60% fallback band.
_FALLBACK_WINDOW_FRACTION = 0.4

SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920


class ShortsFFmpeg(FFmpegWrapper):
    """FFmpeg operations used only by the Shorts/Reels assembly path."""

    def detect_motion_window(
        self, clip_path: str, clip_duration: float, window: float
    ) -> tuple[float, str]:
        """Return (start_time, method) for the *window*-second slice of *clip_path*
        with the highest motion, sampled at low resolution via scene-change scores.

        Falls back to a window starting 40% into the clip (within the spec's 20-60%
        band) on any ffmpeg error or if analysis exceeds _MOTION_DETECT_TIMEOUT seconds.
        """
        usable = max(0.0, clip_duration - window)
        if usable <= 0:
            return 0.0, "fallback"
        try:
            cmd = [
                self._ffmpeg, "-y",
                "-i", clip_path,
                "-vf", (
                    f"scale={_MOTION_SAMPLE_WIDTH}:-1,"
                    "select='gt(scene\\,0.1)',metadata=print"
                ),
                "-an", "-f", "null", "-",
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_MOTION_DETECT_TIMEOUT,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip())
            best_time = self._best_scene_time(result.stderr, usable)
            return best_time, "motion"
        except (subprocess.TimeoutExpired, Exception) as exc:
            _log.info("detect_motion_window: falling back for %s (%s)", clip_path, exc)
            return round(usable * _FALLBACK_WINDOW_FRACTION, 2), "fallback"

    @staticmethod
    def _best_scene_time(ffmpeg_stderr: str, usable: float) -> float:
        """Parse 'pts_time:X' markers from ffmpeg's scene-metadata stderr and return
        the latest one that still leaves room for a full window, or the fallback
        point if none were found."""
        times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", ffmpeg_stderr)]
        candidates = [t for t in times if t <= usable]
        if not candidates:
            return round(usable * _FALLBACK_WINDOW_FRACTION, 2)
        return round(max(candidates), 2)

    def vertical_convert(self, input_path: str, output_path: str, strategy: str) -> None:
        """Convert *input_path* to a 1080x1920 vertical video.

        strategy='center_crop': scale to fill the target frame, crop the excess width.
        strategy='blur_pad': blurred scaled-fill copy behind an aspect-fit foreground.
        """
        if strategy == "blur_pad":
            filter_complex = (
                f"[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={SHORTS_WIDTH}:{SHORTS_HEIGHT},gblur=sigma=20[bg];"
                f"[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
            )
        else:
            filter_complex = (
                f"[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={SHORTS_WIDTH}:{SHORTS_HEIGHT}[vout]"
            )
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"vertical_convert({strategy}) → {output_path!r}")

    def apply_ken_burns(
        self, input_path: str, output_path: str, duration: float, direction: str, pan: bool
    ) -> None:
        """Apply a slow zoompan (Ken Burns) effect over the exact *duration* of the clip.

        direction='in' zooms 1.0→1.08, direction='out' zooms 1.08→1.0. When *pan* is
        True, a slight horizontal pan is layered on top of the zoom. The transform
        completes over exactly *duration* seconds (d=frames at the target fps).
        """
        fps = 30
        frames = max(1, round(duration * fps))
        if direction == "in":
            zoom_expr = "min(zoom+0.0015,1.08)"
        else:
            zoom_expr = "if(eq(on,1),1.08,max(zoom-0.0015,1.0))"
        if pan:
            x_expr = f"iw/2-(iw/zoom/2)+(on/{frames})*40"
        else:
            x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
        zoompan = (
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={SHORTS_WIDTH}x{SHORTS_HEIGHT}:fps={fps}"
        )
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-vf", zoompan,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_ken_burns({direction}) → {output_path!r}")

    def concat_segments_video_only(self, input_paths: list[str], output_path: str) -> None:
        """Concatenate already-vertical, already-Ken-Burns'd segment videos (video only)."""
        n = len(input_paths)
        concat_inputs = "".join(f"[{i}:v]" for i in range(n))
        filter_complex = f"{concat_inputs}concat=n={n}:v=1:a=0[vout]"
        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_segments_video_only → {output_path!r}")

    def mux_shorts_audio(self, video_path: str, audio_path: str, output_path: str) -> None:
        """Mux the concatenated vertical video with the TTS audio track.

        Explicit -map discipline identical to FFmpegWrapper.mux_audio_video: video
        from *video_path* only, audio from *audio_path* only — never let ffmpeg
        auto-pick an audio stream from source footage.
        """
        result = subprocess.run(
            [
                self._ffmpeg, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                output_path,
            ],
            capture_output=True,
            text=True,
        )
        self._check(result, f"mux_shorts_audio → {output_path!r}")
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/bin/python -c "from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg; ShortsFFmpeg()"`
Expected: No output, exit code 0 (constructing it just resolves the ffmpeg/ffprobe binary paths via the inherited `__init__`).

- [ ] **Step 3: Commit**

```bash
git add docu_studio/shorts/shorts_ffmpeg.py
git commit -m "feat(shorts): add ShortsFFmpeg subclass for vertical/Ken-Burns/mux ops"
```

---

### Task 9: `shorts_assembly.py` — audio-first footage assembly orchestration

**Files:**
- Create: `docu_studio/shorts/shorts_assembly.py`

**Interfaces:**
- Consumes: `Segment`, `plan_cuts`, `choose_crop_strategy`, `MAX_SEGMENT_DURATION` (Task 2); `WordTiming` (Task 4); `ShortsScript` (Task 6/7); `ShortsFFmpeg` (Task 8); `docu_studio.adapters.footage.base.FootageProvider` (existing, unedited); `docu_studio.pipeline.stages.footage_assembly.download_clip(url: str, dest: str) -> str` (existing public function, reused not edited); `docu_studio.pipeline.events.{LogEvent, LogLevel, ProgressEvent}` (existing).
- Produces: `assemble_short(script, audio_path, audio_duration, timestamps, tier_used, providers, ffmpeg, project_folder, output_path, seed, event_queue) -> None`. Consumed by Task 10 (`shorts_runner.py`).

No dedicated pytest coverage in this task — it's an IO/subprocess-heavy orchestration function exercised by the manual dry-run in Task 12, consistent with how `footage_assembly.run()` itself has no single all-in-one pytest (its pieces are tested individually; the equivalent granular pieces here — `plan_cuts`, `choose_crop_strategy`, timestamp resolution — already have dedicated tests in Tasks 2–5).

- [ ] **Step 1: Write the implementation**

```python
"""Audio-first assembly for Shorts/Reels: footage fetch, windowing, vertical
conversion, Ken Burns, concat + mux — keyed off the measured TTS audio duration.
"""
from __future__ import annotations

import logging
import queue
from pathlib import Path

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages.footage_assembly import download_clip
from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_cuts import MAX_SEGMENT_DURATION, Segment, choose_crop_strategy, plan_cuts
from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg
from docu_studio.shorts.shorts_script_gen import ShortsScript

_log = logging.getLogger(__name__)

_MIN_CLIPS = 6


def _search_dedup(
    providers: list[FootageProvider], queries: list[str], min_duration: float,
) -> list[tuple[str, int, int]]:
    """Search *providers* for each query in *queries*; return deduped
    (url, width, height) tuples in first-seen order."""
    seen: dict[str, tuple[str, int, int]] = {}
    for query in queries:
        for provider in providers:
            try:
                clips = provider.search([query], min_duration=min_duration, page=1)
            except Exception:
                continue
            for clip in clips:
                if clip.url not in seen:
                    seen[clip.url] = (clip.url, clip.width, clip.height)
            if clips:
                break
    return list(seen.values())


def _collect_clips(
    script: ShortsScript, providers: list[FootageProvider], scene_dir: Path,
    event_queue: queue.Queue,
) -> list[dict]:
    """Fetch and download clips for the per-sentence queries, deduped, padded to at
    least _MIN_CLIPS using the topic-level (first) query if short. Every clip is
    searched with min_duration >= MAX_SEGMENT_DURATION so any assigned segment
    always fits inside the downloaded clip. Returns [{path, width, height}, ...]."""
    per_sentence = _search_dedup(providers, script.visual_queries, min_duration=MAX_SEGMENT_DURATION)
    n_needed = max(_MIN_CLIPS, len(script.sentences))

    pool = list(per_sentence)
    if len(pool) < n_needed:
        topic_query = script.visual_queries[0] if script.visual_queries else "documentary footage"
        extra = _search_dedup(providers, [topic_query], min_duration=MAX_SEGMENT_DURATION)
        existing_urls = {p[0] for p in pool}
        for item in extra:
            if item[0] not in existing_urls:
                pool.append(item)
                existing_urls.add(item[0])
            if len(pool) >= n_needed:
                break

    if not pool:
        raise RuntimeError("Shorts assembly: no footage found for any query.")

    downloaded: list[dict] = []
    for i, (url, width, height) in enumerate(pool):
        dest = str(scene_dir / f"short_clip_{i:03d}.mp4")
        try:
            download_clip(url, dest)
        except Exception:
            continue
        downloaded.append({"path": dest, "width": width, "height": height})

    if not downloaded:
        raise RuntimeError("Shorts assembly: all footage downloads failed.")

    event_queue.put(LogEvent(
        message=f"Shorts footage: {len(downloaded)} clips downloaded (target {n_needed})",
        level=LogLevel.INFO,
    ))
    return downloaded


def _sentence_start_times(script: ShortsScript, timestamps: list[WordTiming]) -> list[float]:
    """Return the start time of each sentence's first word, given a flat *timestamps*
    list aligned word-for-word to the concatenation of *script.sentences*."""
    starts: list[float] = []
    cursor = 0
    for sentence in script.sentences:
        word_count = len(sentence.split())
        if cursor >= len(timestamps) or word_count == 0:
            break
        starts.append(timestamps[cursor].start)
        cursor += word_count
    return starts


def _snap_to_sentences(segments: list[Segment], sentence_starts: list[float]) -> list[Segment]:
    if not sentence_starts:
        return segments
    snapped = []
    for seg in segments:
        nearest = min(sentence_starts, key=lambda t: abs(t - seg.start))
        snapped.append(Segment(index=seg.index, start=nearest, duration=seg.duration, clip_index=seg.clip_index))
    return snapped


def assemble_short(
    script: ShortsScript,
    audio_path: str,
    audio_duration: float,
    timestamps: list[WordTiming],
    tier_used: str,
    providers: list[FootageProvider],
    ffmpeg: ShortsFFmpeg,
    project_folder: Path,
    output_path: Path,
    seed: int,
    event_queue: queue.Queue,
) -> None:
    """Build the final vertical short: fetch footage, plan cuts, window/convert/
    Ken-Burns each segment, concat, and mux with the TTS audio track."""
    scene_dir = project_folder / "video"
    scene_dir.mkdir(exist_ok=True)

    event_queue.put(ProgressEvent(stage="Short Footage", message="Searching stock footage…"))
    clips = _collect_clips(script, providers, scene_dir, event_queue)

    segments = plan_cuts(total_duration=audio_duration, n_clips=len(clips), seed=seed)
    if tier_used == "tier1_native":
        sentence_starts = _sentence_start_times(script, timestamps)
        segments = _snap_to_sentences(segments, sentence_starts)

    event_queue.put(ProgressEvent(stage="Short Assembly", message=f"Building {len(segments)} segments…"))

    segment_paths: list[str] = []
    for seg in segments:
        clip = clips[seg.clip_index]
        raw_duration = ffmpeg.get_duration(clip["path"])
        window = max(2.0, min(4.0, seg.duration))
        start, method = ffmpeg.detect_motion_window(clip["path"], raw_duration, window)
        _log.info(
            "Segment %d: clip=%s window_method=%s start=%.2f",
            seg.index, clip["path"], method, start,
        )

        windowed = str(scene_dir / f"seg_{seg.index:03d}_window.mp4")
        ffmpeg.trim_clip(clip["path"], start, seg.duration, windowed)

        strategy = choose_crop_strategy(clip["width"], clip["height"])
        vertical = str(scene_dir / f"seg_{seg.index:03d}_vertical.mp4")
        ffmpeg.vertical_convert(windowed, vertical, strategy)
        _log.info("Segment %d: crop_strategy=%s", seg.index, strategy)

        direction = "in" if seg.index % 2 == 0 else "out"
        pan = seg.index % 3 == 0
        kenburns = str(scene_dir / f"seg_{seg.index:03d}_kb.mp4")
        ffmpeg.apply_ken_burns(vertical, kenburns, seg.duration, direction, pan)

        segment_paths.append(kenburns)

    event_queue.put(ProgressEvent(stage="Short Mux", message="Concatenating and muxing final short…"))
    concat_path = str(scene_dir / "short_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)
    ffmpeg.mux_shorts_audio(concat_path, audio_path, str(output_path))

    event_queue.put(LogEvent(
        message=f"Short assembled: {len(segments)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/bin/python -c "from docu_studio.shorts.shorts_assembly import assemble_short"`
Expected: No output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add docu_studio/shorts/shorts_assembly.py
git commit -m "feat(shorts): add audio-first assembly orchestration"
```

---

### Task 10: `ShortsRunner` — background orchestrator thread

**Files:**
- Create: `docu_studio/shorts/shorts_runner.py`

**Interfaces:**
- Consumes: `ShortsConfig` (Task 1); `generate_shorts_script` (Task 7); `get_word_timestamps` (Task 5); `assemble_short` (Task 9); `ShortsFFmpeg` (Task 8); `docu_studio.adapters.{llm,tts,footage}.base.*` (existing); `docu_studio.history.run_history.{RunRecord, save_run}` (existing, read/write reuse only); `docu_studio.output.project_folder.create_project_folder` (existing); `docu_studio.pipeline.events.{ErrorEvent, LogEvent, LogLevel, ProgressEvent}` (existing).
- Produces: `ShortsRunner(threading.Thread)` with public attributes matching `PipelineRunner`'s shape so `Bridge._translate_events` (unmodified) works transparently: `.event_queue: queue.Queue`, `.cancel_event: threading.Event`, `._final_video_path: Path | None`, `._project_folder: Path | None`, `.run() -> None`. Constructor: `ShortsRunner(topic, duration_seconds, llm, tts, footage_providers, output_base, sensitive_keys=None, seed=None)`. Consumed by Task 11 (`Bridge.start_shorts_run`).

- [ ] **Step 1: Write the implementation**

```python
"""ShortsRunner — background thread that orchestrates the Shorts/Reels pipeline.

Mirrors docu_studio.pipeline.runner.PipelineRunner's public shape (event_queue,
cancel_event, _final_video_path, _project_folder, run()) so the existing
Bridge._translate_events() works unmodified for both run types. Does not import
from pipeline.runner — a plain queue.Queue is used here rather than PipelineRunner's
private _TeeQueue log-teeing helper, since per-run pipeline_log.txt teeing is not
required for Shorts by this task; project folder + history integration are reused.
"""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.shorts.capability_resolvers import get_word_timestamps
from docu_studio.shorts.shorts_assembly import assemble_short
from docu_studio.shorts.shorts_config import ShortsConfig
from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg
from docu_studio.shorts.shorts_script_gen import generate_shorts_script


class ShortsRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ShortsRunner(threading.Thread):
    def __init__(
        self,
        topic: str,
        duration_seconds: int,
        llm: LLMProvider,
        tts: TTSProvider,
        footage_providers: list[FootageProvider],
        output_base: Path,
        sensitive_keys: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        super().__init__(daemon=True, name="ShortsRunner")
        self.config = ShortsConfig(topic=topic, duration_seconds=duration_seconds)
        self.llm = llm
        self.tts = tts
        self.footage_providers = footage_providers
        self.output_base = output_base
        self._sensitive_keys: list[str] = sensitive_keys or []
        self._seed = seed if seed is not None else int(datetime.now().timestamp())

        self.event_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()

        self._status = ShortsRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = ShortsRunStatus.FAILED
        finally:
            self._save_history()
            self.event_queue.put(None)

    def _execute(self) -> None:
        self._project_folder = create_project_folder(
            self.config.topic, self._started_at, self.output_base
        )
        ffmpeg = ShortsFFmpeg()

        self.event_queue.put(ProgressEvent(
            stage="Short Script", message=f"Writing short script for '{self.config.topic}'…",
        ))
        script = generate_shorts_script(self.config.topic, self.config.duration_seconds, self.llm)
        (self._project_folder / "script.md").write_text(script.text, encoding="utf-8")
        self.event_queue.put(LogEvent(
            message=f"Short script generated ({len(script.text.split())} words, "
                    f"{len(script.sentences)} sentences)",
            level=LogLevel.INFO,
        ))
        if self._cancelled():
            return

        self.event_queue.put(ProgressEvent(stage="Short Audio", message="Synthesizing voiceover…"))
        audio_path = str(self._project_folder / "audio" / "short.mp3")
        audio_duration = self.tts.synthesize(script.text, audio_path)
        self.event_queue.put(LogEvent(message=f"Voiceover: {audio_duration:.2f}s", level=LogLevel.INFO))
        if self._cancelled():
            return

        timestamps, tier_used = get_word_timestamps(audio_path, script.text, self.tts)
        self.event_queue.put(LogEvent(message=f"Word timing resolver: {tier_used}", level=LogLevel.INFO))
        if self._cancelled():
            return

        output_path = self._project_folder / "short_final.mp4"
        assemble_short(
            script=script,
            audio_path=audio_path,
            audio_duration=audio_duration,
            timestamps=timestamps,
            tier_used=tier_used,
            providers=self.footage_providers,
            ffmpeg=ffmpeg,
            project_folder=self._project_folder,
            output_path=output_path,
            seed=self._seed,
            event_queue=self.event_queue,
        )
        if self._cancelled():
            return

        self._final_video_path = output_path
        self._status = ShortsRunStatus.COMPLETED
        actual_duration = ffmpeg.get_duration(str(output_path))
        self.event_queue.put(ProgressEvent(
            stage="Done",
            message=(
                f"Short completed: {actual_duration:.1f}s actual vs "
                f"{self.config.duration_seconds}s requested."
            ),
        ))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = ShortsRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic=self.config.topic,
                mode="shorts",
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source="user_supplied",
                fallback_triggered=False,
            )
            save_run(record)
        except Exception:
            pass  # history failure must never crash the runner
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/bin/python -c "from docu_studio.shorts.shorts_runner import ShortsRunner"`
Expected: No output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add docu_studio/shorts/shorts_runner.py
git commit -m "feat(shorts): add ShortsRunner orchestrator"
```

---

### Task 11: GUI wiring — mode card, config screen, Bridge method

**Files:**
- Modify: `docu_studio/gui/web/index.html`
- Modify: `docu_studio/gui/web/app.js`
- Modify: `docu_studio/gui/bridge.py`
- Modify: `docu_studio/gui/webview_app.py`

**Interfaces:**
- Consumes: `ShortsRunner` (Task 10); existing `Bridge.{_settings, _event_q, _runner, _run_thread, _translate_events}` (unmodified — reused as-is since `ShortsRunner` matches `PipelineRunner`'s attribute shape).
- Produces: `Bridge.start_shorts_run(config: dict) -> dict` (new method, additive). `startConfig('short')`, `updateShortsDurationHint()` in `app.js` (new functions, additive). `Bridge.start_run` and all existing `app.js` functions are untouched.

- [ ] **Step 1: Add the third mode card to `index.html`**

In `docu_studio/gui/web/index.html`, find the mode-cards grid (currently two `<div onclick="startConfig(...)">` cards) and add a third card after the Full Auto card, inside the same `grid grid-cols-2 gap-6` container:

```html
        <!-- Short / Reel -->
        <div onclick="startConfig('short')" class="anim-card col-span-2 bg-card border border-border rounded-xl p-8 hover:border-rose-400 transition-colors cursor-pointer">
          <div class="text-xs font-semibold tracking-widest text-rose-400">SHORT / REEL MODE</div>
          <div class="text-xl font-semibold text-white mt-2">Vertical short-form video</div>
          <p class="text-sm text-dim mt-3 leading-relaxed">Enter a topic and pick a length from 15 to 60 seconds. The app writes a hook-driven script, records voiceover, and assembles a 9:16 vertical cut with Ken Burns motion — ready for Shorts, Reels, or TikTok.</p>
          <button class="mt-6 bg-rose-500 text-white font-semibold text-sm px-5 py-2.5 rounded-lg hover:bg-rose-600 transition-colors pointer-events-none">Start short run →</button>
        </div>
```

Add its entrance-animation delay next to the existing `.grid.grid-cols-2 > .anim-card:nth-child(1/2)` rules in the `<style>` block:

```css
    .grid.grid-cols-2 > .anim-card:nth-child(3) { animation-delay: 140ms; }
```

- [ ] **Step 2: Add the shorts duration/aspect config blocks to `index.html`**

Wrap the existing documentary duration block (the `<div class="mt-6">` containing `duration-input`/`duration-seconds-input`) with `id="doc-duration-row"`:

```html
        <!-- Duration (documentary) -->
        <div id="doc-duration-row" class="mt-6">
          <label class="text-sm font-medium text-dim block">Target duration</label>
          <div class="mt-2 flex items-center">
            <input id="duration-input" type="number" min="1" max="120" value="5"
              class="w-24 bg-input border border-border rounded-lg px-4 py-3 text-white text-sm text-center focus:border-accent focus:outline-none">
            <span class="text-sm text-dim ml-2 mr-4">min</span>
            <input id="duration-seconds-input" type="number" min="0" max="59" step="1" value="0"
              class="w-24 bg-input border border-border rounded-lg px-4 py-3 text-white text-sm text-center focus:border-accent focus:outline-none">
            <span class="text-sm text-dim ml-2">sec</span>
          </div>
          <div id="duration-hint" class="mt-3 text-xs text-faint">Target: 5 min 0 s ≈ 750 words of narration</div>
        </div>
```

Immediately after that block (still inside the same card, before the "Start button"), add:

```html
        <!-- Duration (short/reel) -->
        <div id="short-duration-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Target duration</label>
          <div class="mt-2 flex items-center gap-4">
            <input id="shorts-duration-slider" type="range" min="15" max="60" step="1" value="30"
              class="flex-1 accent-accent">
            <span id="shorts-duration-label" class="text-sm font-semibold text-accent w-14">30 s</span>
          </div>
          <div id="shorts-duration-hint" class="mt-3 text-xs text-faint">Target: 30s ≈ 85 words of narration</div>
        </div>

        <!-- Aspect (short/reel, fixed) -->
        <div id="aspect-row" class="mt-4" style="display:none">
          <label class="text-sm font-medium text-dim block">Aspect ratio</label>
          <div class="mt-2 text-sm text-dim bg-input border border-border rounded-lg px-4 py-2.5">9:16 vertical · 1080 × 1920 (fixed)</div>
        </div>
```

- [ ] **Step 3: Add `startConfig('short')` branch and `updateShortsDurationHint` to `app.js`**

In `docu_studio/gui/web/app.js`, extend `startConfig` (adds an `else if` branch; the `guided`/`else` branches are unchanged) and toggle the new rows:

```javascript
function startConfig(mode) {
  _runMode = mode;
  const badge = _q('config-mode-badge');
  if (mode === 'guided') {
    badge.textContent = 'Guided Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-[#0c2d42] text-sky-400';
    _q('topic-row').style.display = '';
  } else if (mode === 'short') {
    badge.textContent = 'Short / Reel Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-rose-900/40 text-rose-300';
    _q('topic-row').style.display = '';
  } else {
    badge.textContent = 'Full Auto Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-purple-900/40 text-purple-300';
    _q('topic-row').style.display = 'none';
  }
  _q('doc-duration-row').style.display = mode === 'short' ? 'none' : '';
  _q('short-duration-row').style.display = mode === 'short' ? '' : 'none';
  _q('aspect-row').style.display = mode === 'short' ? '' : 'none';
  showScreen('config');
}
```

Add a new function near `updateDurationHint`:

```javascript
function updateShortsDurationHint() {
  const secs = parseInt(_q('shorts-duration-slider').value) || 30;
  _q('shorts-duration-label').textContent = secs + ' s';
  const words = Math.round((secs / 60) * 170);
  _q('shorts-duration-hint').textContent = `Target: ${secs}s ≈ ${words} words of narration`;
}
```

Add an early-return branch at the very top of `startRun()` (before the existing `minutes`/`seconds` reads) — the rest of the function is untouched:

```javascript
async function startRun() {
  const topic = (_q('topic-input')?.value || '').trim();
  if (_runMode === 'short') {
    if (!topic) {
      _q('topic-input').focus();
      _q('topic-input').classList.add('border-red-500');
      return;
    }
    const secs = parseInt(_q('shorts-duration-slider').value) || 30;
    showScreen('progress');
    _resetProgress();
    startPolling();
    const res = await window.pywebview.api.start_shorts_run({ topic, duration_seconds: secs });
    if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
    return;
  }
  const minutes = parseInt(_q('duration-input').value) || 0;
  const seconds = _clampSeconds(parseInt(_q('duration-seconds-input').value) || 0);
  if (_runMode === 'guided' && !topic) {
    _q('topic-input').focus();
    _q('topic-input').classList.add('border-red-500');
    return;
  }
  if (minutes * 60 + seconds <= 0) {
    _q('duration-input').focus();
    _q('duration-input').classList.add('border-red-500');
    return;
  }
  showScreen('progress');
  _resetProgress();
  startPolling();
  const res = await window.pywebview.api.start_run({
    mode: _runMode, topic, duration_minutes: minutes, duration_seconds: seconds,
  });
  if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
}
```

In the `DOMContentLoaded` init block, add (do not remove or reorder existing lines):

```javascript
  const shortsDur = _q('shorts-duration-slider');
  if (shortsDur) shortsDur.addEventListener('input', updateShortsDurationHint);
```

- [ ] **Step 4: Add `Bridge.start_shorts_run` to `bridge.py`**

In `docu_studio/gui/bridge.py`, add a new method after `start_run` (does not modify `start_run`):

```python
    def start_shorts_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            from docu_studio.adapters.footage.factory import build_footage_providers
            from docu_studio.adapters.llm.factory import build_llm
            from docu_studio.adapters.tts.factory import build_tts
            from docu_studio.shorts.shorts_runner import ShortsRunner

            s = self._settings
            provider = getattr(s, "llm_provider", "Anthropic")
            model    = getattr(s, "llm_model",    "claude-sonnet-4-5")
            key_map  = {
                "Anthropic":  key_cache.get("docu_studio_anthropic"),
                "OpenAI":     key_cache.get("docu_studio_openai"),
                "OpenRouter": key_cache.get("docu_studio_openrouter"),
                "Groq":       key_cache.get("docu_studio_groq"),
            }
            llm_key     = key_map.get(provider, "") or ""
            tts_prov    = getattr(s, "tts_provider", "elevenlabs")
            tts_key     = (
                key_cache.get("docu_studio_elevenlabs")
                if tts_prov == "elevenlabs"
                else key_cache.get("docu_studio_deepgram_key")
            )
            pexels_key  = key_cache.get("docu_studio_pexels")
            pixabay_key = key_cache.get("docu_studio_pixabay")
            coverr_key  = key_cache.get("docu_studio_coverr")

            llm = build_llm(provider, llm_key, model)
            tts = build_tts(
                tts_prov, tts_key or "",
                getattr(s, "deepgram_voice", "aura-asteria-en"),
            )
            footage_list = build_footage_providers(
                getattr(s, "footage_primary",   "pexels"),
                getattr(s, "footage_fallback",  "pixabay"),
                pexels_key  or "",
                pixabay_key or "",
                coverr_key  or "",
                fallback2=getattr(s, "footage_fallback2", "none"),
            )

            while not self._event_q.empty():
                try:
                    self._event_q.get_nowait()
                except queue.Empty:
                    break

            output_base = (
                Path(s.output_folder)
                if getattr(s, "output_folder", None)
                else Path.home() / "DocuStudio"
            )
            duration_seconds = int(config.get("duration_seconds", 30))

            self._runner = ShortsRunner(
                topic=config.get("topic", ""),
                duration_seconds=duration_seconds,
                llm=llm,
                tts=tts,
                footage_providers=footage_list,
                output_base=output_base,
                sensitive_keys=[
                    v for v in [llm_key, tts_key, pexels_key, pixabay_key, coverr_key] if v
                ],
            )

            def _run() -> None:
                try:
                    self._runner.run()
                except Exception as exc:
                    import traceback
                    self._event_q.put({
                        "type": "error",
                        "message": str(exc) + "\n" + traceback.format_exc(),
                    })

            self._run_thread = threading.Thread(target=_run, daemon=True)
            self._run_thread.start()
            threading.Thread(target=self._translate_events, daemon=True).start()
            return {"ok": True}

        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}
```

- [ ] **Step 5: Bump the cache buster in `webview_app.py`**

In `docu_studio/gui/webview_app.py`, change:

```python
    the_url = str(WEB_DIR / "index.html") + "?v=7"
```

to:

```python
    the_url = str(WEB_DIR / "index.html") + "?v=8"
```

- [ ] **Step 6: Verify the app launches and the new mode is reachable**

Run: `DISPLAY=:1 .venv/bin/python -m docu_studio`
Expected: window opens on the main screen with three mode cards (Guided, Full Auto, Short/Reel spanning the width below). Click "Short / Reel Mode" → config screen shows topic input, the 15-60s slider (default 30s, updating its label live), and the fixed "9:16 vertical · 1080 × 1920" badge — the minute/second inputs from the documentary flow are hidden. Click back to main, click "Guided Mode" → confirm the original minute/second duration UI still appears unchanged (regression check that the documentary flow is untouched). Close the app after confirming.

- [ ] **Step 7: Commit**

```bash
git add docu_studio/gui/web/index.html docu_studio/gui/web/app.js docu_studio/gui/bridge.py docu_studio/gui/webview_app.py
git commit -m "feat(shorts): wire Short/Reel mode into the GUI"
```

---

### Task 12: Full-suite verification and dry-run report

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m pytest -q --ignore=tests/integration/test_edge_tts_adapter.py`
Expected: `24 failed, 150 passed` **plus** all new shorts tests passing (Tasks 1–7 add roughly 44 new tests: 5 + 11 + 6 + 7 + 4 + 8 + 4 — recount exact totals from each task's actual run). Total failed count must remain exactly 24 (no new failures); total passed count increases by the number of new shorts tests.

Run: `.venv/bin/python -m pytest -q` (with the known collection error included)
Expected: same 1 collection error (`tests/integration/test_edge_tts_adapter.py`, pre-existing, unrelated to this work) plus the same 24 failed / expanded passed count.

- [ ] **Step 2: Dry-run `plan_cuts` + a synthetic assembly-shape check (no API calls, no ffmpeg)**

Run this inline to confirm the cut-planning and crop-strategy logic behaves sensibly end-to-end on synthetic inputs, without spending API credits or invoking ffmpeg:

```bash
.venv/bin/python -c "
from docu_studio.shorts.shorts_cuts import plan_cuts, choose_crop_strategy
from docu_studio.shorts.capability_resolvers import estimate_word_timestamps

# Simulate a 32-second short with 7 fetched clips.
segments = plan_cuts(total_duration=32.0, n_clips=7, seed=2026)
print(f'{len(segments)} segments, total={sum(s.duration for s in segments):.2f}s')
for s in segments:
    print(f'  seg {s.index}: start={s.start:.2f} dur={s.duration:.2f} clip={s.clip_index}')

print('center_crop (1920x1080):', choose_crop_strategy(1920, 1080))
print('blur_pad (3840x1080):', choose_crop_strategy(3840, 1080))

script = 'Ninety percent of the ocean floor is unmapped. That is more unknown territory than the surface of Mars. We know the moon better than our own seabed.'
timestamps = estimate_word_timestamps(script, 32.0)
print(f'{len(timestamps)} words, spans 0.00 to {timestamps[-1].end:.2f}s')
"
```

Expected: prints a segment list whose durations sum to 32.00s (last one trimmed), varied lengths, `center_crop` / `blur_pad` printed correctly for the two sample resolutions, and a word-timestamp list spanning exactly to 32.00s.

- [ ] **Step 3: Report back**

Summarize for the user: files created (list the full `docu_studio/shorts/` package plus the 4 modified GUI files), which TTS adapters natively expose timestamps (none — gtts/elevenlabs/deepgram all confirmed to lack it, Tier 1 is a scaffold), the resolver tier that fires in practice (`tier3_estimated`, logged via `_log.info` in `capability_resolvers.py` and surfaced as a `LogEvent` in `ShortsRunner`), and the Step 2 dry-run output.

- [ ] **Step 4: Commit (if Step 1 required any fixes)**

Only if Step 1 uncovered a regression requiring a code fix:

```bash
git add -A
git commit -m "fix(shorts): resolve test regression found during full-suite verification"
```

If no fixes were needed, skip this step — nothing to commit.
