# Clip Story Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of Clip Story — a new pipeline that compiles user-uploaded video
files into a narrated video where each clip's own (trimmed) duration is authoritative and
narration is fit into it via a three-layer duration-fit algorithm (script sizing → bounded
atempo → halt-and-report).

**Architecture:** New top-level package `docu_studio/clipstory/` mirroring the
`shorts/`/`slideshow/` package convention (not `pipeline/stages/`). Reuses
`docu_studio/common/` (`ffmpeg_finalize`, and after this plan's Task 1, `tts_calibration`)
and the existing `FFmpegWrapper`/`LLMProvider`/`TTSProvider` bases. GUI wiring is additive
in `bridge.py`/`webview_app.py`/`web/app.js`/`web/index.html`, following the exact pattern
Shorts and Slideshow already established.

**Tech Stack:** Python 3.11+, ffmpeg (via `imageio_ffmpeg`), pytest, pywebview/JS frontend.

## Global Constraints

- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files — new adapter files are
  fine), `history/`, `licensing.py`, or existing test files unless fixing an actual bug in
  them.
- Correct venv is `.venv/`, never `venv/`. Restart before testing any GUI change:
  `pkill -f docu_studio 2>/dev/null; DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Work happens on branch/worktree `clipstory-phase1`. Commit incrementally. Do not push
  without explicit go-ahead.
- Bump the cache-busting `?v=N` in `docu_studio/gui/webview_app.py:33` from `?v=12` to
  `?v=13` after the HTML/JS task (Task 9) — current value confirmed by reading the file.
- Confirm the pre-existing test failure/collection-error baseline with a fresh, isolated
  `pytest` run before Task 1 — do not carry over the "24" figure from the design spec
  without re-measuring it yourself.
- Spec reference: `docs/superpowers/specs/2026-07-13-clipstory-phase1-design.md` — every
  task below implements a specific section of that spec; consult it for the full rationale
  behind any decision that seems surprising.
- Layer 3 halts are surfaced via the existing `ErrorEvent(message, fatal=True)` mechanism
  (`docu_studio/pipeline/events.py`) already wired through `Bridge._to_js_event` and
  `app.js`'s `_handleEvent`'s `ev.type === 'error'` branch — do not build a new "blocking
  panel" UI component; the existing error display already renders the full message text
  (including embedded newlines) in the log area.

---

### Task 0: Baseline check and worktree setup

**Files:** none (verification only).

**Interfaces:** N/A — this task produces no code, only a recorded baseline number used to
judge Task-by-task regressions.

- [ ] **Step 1: Confirm worktree/branch exists**

Run: `git worktree list`
Expected: a worktree for branch `clipstory-phase1` exists (created via
`superpowers:using-git-worktrees` at execution start). If it does not exist yet, create it
before proceeding with Task 1.

- [ ] **Step 2: Run the full test suite fresh, record the baseline**

Run: `cd <worktree-path> && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -30`
Expected: some number of passed tests and a baseline count of pre-existing failures/errors
(do not assume it is 24 — read the actual output). Write this number down; it is the
number every subsequent task's "no new failures" check compares against.

---

### Task 1: Promote TTS calibration to `docu_studio/common/tts_calibration.py`

**Files:**
- Create: `docu_studio/common/tts_calibration.py`
- Delete: `docu_studio/shorts/shorts_tts_calibration.py`
- Modify: `docu_studio/shorts/shorts_script_gen.py:16`
- Modify: `docu_studio/shorts/shorts_runner.py:30`
- Create: `tests/unit/test_tts_calibration.py`
- Delete: `tests/unit/test_shorts_tts_calibration.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_wpm(provider: str, voice: str, default: float) -> float`,
  `record_measurement(provider: str, voice: str, word_count: int,
  measured_duration_seconds: float) -> float`, `calibration_key(provider: str, voice: str)
  -> str`, `load_calibration() -> dict[str, float]`, `CALIBRATION_MIN_WPM: float`,
  `CALIBRATION_MAX_WPM: float` — all now importable from
  `docu_studio.common.tts_calibration` (Task 4 imports `get_wpm` from here).

- [ ] **Step 1: Create `docu_studio/common/tts_calibration.py` with the moved content**

```python
"""Persisted per-(TTS provider, voice) words-per-minute calibration.

Shared by Shorts and Clip Story (and any future pipeline needing to target a word
count from a duration): the 170 WPM default used for word-target math assumes a
brisk TTS voice; several configured providers/voices actually speak closer to
120-130 WPM. This module stores a rolling measured WPM per provider+voice (JSON
file in the OS config dir, mirroring history/run_history.py's atomic-write
pattern) so script generation can target the pace the configured voice actually
produces.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from docu_studio.platform_layer import config_dir

_log = logging.getLogger(__name__)

_CALIBRATION_FILE = "shorts_tts_calibration.json"

CALIBRATION_MIN_WPM = 90.0
CALIBRATION_MAX_WPM = 220.0

# Exponential moving average weight for each new measurement — smooths out
# per-run noise (short scripts, misdetected silences) while still tracking
# real drift in a voice's pace over time.
_EMA_ALPHA = 0.3


def _clamp(wpm: float) -> float:
    return max(CALIBRATION_MIN_WPM, min(CALIBRATION_MAX_WPM, wpm))


def calibration_key(provider: str, voice: str) -> str:
    return f"{provider}:{voice}"


def _calibration_path() -> Path:
    return config_dir() / _CALIBRATION_FILE


def load_calibration() -> dict[str, float]:
    path = _calibration_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}


def _save_calibration(data: dict[str, float]) -> None:
    path = _calibration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        tmp.write(json.dumps(data, indent=2))
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def get_wpm(provider: str, voice: str, default: float) -> float:
    """Return the stored WPM for *provider*+*voice*, clamped, or *default*."""
    key = calibration_key(provider, voice)
    stored = load_calibration().get(key)
    if stored is None:
        return default
    return _clamp(stored)


def record_measurement(
    provider: str, voice: str, word_count: int, measured_duration_seconds: float
) -> float:
    """Compute actual WPM from a completed synthesis and roll it into the
    stored calibration for *provider*+*voice*. Returns the newly measured
    (unsmoothed) WPM for logging."""
    if word_count <= 0 or measured_duration_seconds <= 0:
        return 0.0
    measured_wpm = word_count / measured_duration_seconds * 60
    key = calibration_key(provider, voice)
    data = load_calibration()
    previous = data.get(key)
    blended = measured_wpm if previous is None else (
        _EMA_ALPHA * measured_wpm + (1 - _EMA_ALPHA) * previous
    )
    data[key] = _clamp(blended)
    try:
        _save_calibration(data)
    except Exception as exc:
        _log.warning("Failed to persist TTS calibration for %s: %s", key, exc)
    return measured_wpm
```

Note: `_CALIBRATION_FILE` keeps the literal filename `shorts_tts_calibration.json` —
renaming the on-disk file would silently discard every user's existing calibration data,
which is unrelated to this move and out of scope.

- [ ] **Step 2: Delete the old module**

Run: `rm "docu_studio/shorts/shorts_tts_calibration.py"`

- [ ] **Step 3: Update the two import sites**

In `docu_studio/shorts/shorts_script_gen.py`, change line 16 from:
```python
from docu_studio.shorts.shorts_tts_calibration import get_wpm
```
to:
```python
from docu_studio.common.tts_calibration import get_wpm
```

In `docu_studio/shorts/shorts_runner.py`, change line 30 from:
```python
from docu_studio.shorts.shorts_tts_calibration import record_measurement
```
to:
```python
from docu_studio.common.tts_calibration import record_measurement
```

- [ ] **Step 4: Create the ported test file at the new location**

```python
"""Unit tests for common/tts_calibration: persisted per-(provider, voice) WPM."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from docu_studio.common.tts_calibration import (
    CALIBRATION_MAX_WPM,
    CALIBRATION_MIN_WPM,
    calibration_key,
    get_wpm,
    load_calibration,
    record_measurement,
)


def _patched(tmp_path: Path):
    return patch("docu_studio.common.tts_calibration.config_dir", return_value=tmp_path)


class TestCalibrationKey:
    def test_key_combines_provider_and_voice(self) -> None:
        assert calibration_key("elevenlabs", "Rachel") == "elevenlabs:Rachel"


class TestGetWpm:
    def test_default_path_when_no_calibration_exists(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            assert get_wpm("elevenlabs", "Rachel", default=170.0) == 170.0

    def test_returns_stored_value_after_measurement(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("elevenlabs", "Rachel", word_count=100, measured_duration_seconds=50.0)
            assert get_wpm("elevenlabs", "Rachel", default=170.0) == 120.0

    def test_different_voice_keys_are_independent(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("elevenlabs", "Rachel", word_count=100, measured_duration_seconds=50.0)
            assert get_wpm("elevenlabs", "Bella", default=170.0) == 170.0


class TestRecordMeasurement:
    def test_round_trip_persists_across_loads(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("deepgram", "aura-asteria-en", word_count=130, measured_duration_seconds=60.0)
            data = load_calibration()
        assert data[calibration_key("deepgram", "aura-asteria-en")] == 130.0

    def test_returns_unsmoothed_measured_wpm(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            measured = record_measurement(
                "deepgram", "aura-asteria-en", word_count=130, measured_duration_seconds=60.0
            )
        assert measured == 130.0

    def test_rolling_average_blends_with_previous_measurement(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("gtts", "default", word_count=100, measured_duration_seconds=60.0)  # 100 wpm
            record_measurement("gtts", "default", word_count=200, measured_duration_seconds=60.0)  # 200 wpm
            stored = get_wpm("gtts", "default", default=170.0)
        # EMA(alpha=0.3): 0.3*200 + 0.7*100 = 130, strictly between the two raw measurements
        assert 100.0 < stored < 200.0

    def test_clamps_to_max_wpm(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("fast_voice", "x", word_count=500, measured_duration_seconds=60.0)  # 500 wpm
            stored = get_wpm("fast_voice", "x", default=170.0)
        assert stored == CALIBRATION_MAX_WPM

    def test_clamps_to_min_wpm(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("slow_voice", "x", word_count=10, measured_duration_seconds=60.0)  # 10 wpm
            stored = get_wpm("slow_voice", "x", default=170.0)
        assert stored == CALIBRATION_MIN_WPM

    def test_zero_duration_is_a_no_op(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            measured = record_measurement("p", "v", word_count=50, measured_duration_seconds=0.0)
            data = load_calibration()
        assert measured == 0.0
        assert data == {}

    def test_zero_word_count_is_a_no_op(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            measured = record_measurement("p", "v", word_count=0, measured_duration_seconds=30.0)
            data = load_calibration()
        assert measured == 0.0
        assert data == {}


class TestLoadCalibration:
    def test_returns_empty_dict_when_no_file(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            assert load_calibration() == {}

    def test_returns_empty_dict_on_corrupt_file(self, tmp_path: Path) -> None:
        (tmp_path / "shorts_tts_calibration.json").write_text("not json", encoding="utf-8")
        with _patched(tmp_path):
            assert load_calibration() == {}
```

- [ ] **Step 5: Delete the old test file**

Run: `rm "tests/unit/test_shorts_tts_calibration.py"`

- [ ] **Step 6: Run tests to verify the move is clean**

Run: `.venv/bin/python -m pytest tests/unit/test_tts_calibration.py tests/unit/test_shorts_script_gen.py -v`
Expected: all pass. `test_shorts_script_gen.py` passing confirms the import-site update in
`shorts_script_gen.py` didn't break existing Shorts behavior.

- [ ] **Step 7: Run the full suite, confirm no new regressions vs. Task 0's baseline**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -10`
Expected: same failure/error count as the Task 0 baseline (the two deleted/created test
files net to zero change in count).

- [ ] **Step 8: Real E2E verification — this is a moved-code change, not skipped as "just mechanical"**

Restart the app and run one real Shorts render end-to-end:
```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio
```
In the GUI: start a Short/Reel run with any topic, let it complete. Then confirm the
calibration file still updates:
```bash
cat ~/.config/docu_studio/shorts_tts_calibration.json 2>/dev/null || cat "$(python3 -c 'import platformdirs; print(platformdirs.user_config_dir("docu_studio", appauthor=False))')/shorts_tts_calibration.json"
```
Expected: the file exists, is valid JSON, and its `mtime` is after the run just completed
(confirms `record_measurement` still persists correctly from the new import path, not just
that the import resolves at collection time).

- [ ] **Step 9: Commit**

```bash
git add docu_studio/common/tts_calibration.py docu_studio/shorts/shorts_script_gen.py \
        docu_studio/shorts/shorts_runner.py tests/unit/test_tts_calibration.py
git rm docu_studio/shorts/shorts_tts_calibration.py tests/unit/test_shorts_tts_calibration.py
git commit -m "refactor(tts): promote shorts_tts_calibration to common/tts_calibration"
```

---

### Task 2: `clipstory_config.py` — `ClipSpec` / `ClipStoryConfig` dataclasses

**Files:**
- Create: `docu_studio/clipstory/__init__.py` (empty, matches `common/`'s convention)
- Create: `docu_studio/clipstory/clipstory_config.py`
- Test: `tests/unit/test_clipstory_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ClipSpec(path: str, trim_in: float, trim_out: float, script_text: str = "",
  use_llm_generation: bool = False)` with `.duration_estimate -> float` property;
  `ClipStoryConfig(topic: str, clips: list[ClipSpec], output_resolution: str = "16:9",
  tts_provider: str = "", tts_voice: str = "")`. Both raise `ValueError` on invalid input.
  Task 4, 6, 7, 8 all construct/consume these two types — signatures above are final.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for clipstory_config: ClipSpec / ClipStoryConfig validation."""
from __future__ import annotations

import pytest

from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig


class TestClipSpec:
    def test_valid_user_written_clip(self) -> None:
        clip = ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hello there.")
        assert clip.duration_estimate == 10.0

    def test_valid_llm_flagged_clip(self) -> None:
        clip = ClipSpec(path="/a.mp4", trim_in=2.0, trim_out=12.5, use_llm_generation=True)
        assert clip.duration_estimate == 10.5

    def test_negative_trim_in_raises(self) -> None:
        with pytest.raises(ValueError, match="trim_in"):
            ClipSpec(path="/a.mp4", trim_in=-1.0, trim_out=10.0, script_text="x")

    def test_trim_out_not_greater_than_trim_in_raises(self) -> None:
        with pytest.raises(ValueError, match="trim_out"):
            ClipSpec(path="/a.mp4", trim_in=5.0, trim_out=5.0, script_text="x")

    def test_trim_out_less_than_trim_in_raises(self) -> None:
        with pytest.raises(ValueError, match="trim_out"):
            ClipSpec(path="/a.mp4", trim_in=5.0, trim_out=2.0, script_text="x")

    def test_both_script_text_and_llm_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot both"):
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="x", use_llm_generation=True)

    def test_neither_script_text_nor_llm_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="either"):
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0)


class TestClipStoryConfig:
    def test_valid_config(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips)
        assert config.output_resolution == "16:9"

    def test_empty_clip_list_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one clip"):
            ClipStoryConfig(topic="Test", clips=[])

    def test_invalid_output_resolution_raises(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        with pytest.raises(ValueError, match="output_resolution"):
            ClipStoryConfig(topic="Test", clips=clips, output_resolution="4:3")

    def test_9_16_output_resolution_accepted(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips, output_resolution="9:16")
        assert config.output_resolution == "9:16"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.clipstory'`.

- [ ] **Step 3: Create the package and implementation**

Create `docu_studio/clipstory/__init__.py` (empty file).

Create `docu_studio/clipstory/clipstory_config.py`:
```python
"""Config dataclasses for Clip Story: one ClipSpec per uploaded video clip, one
ClipStoryConfig for the whole project. Validated at construction time — these are
built at the Bridge boundary from user/GUI input, not mutated afterward except to
fill in generated narration text (see clipstory_script_gen.prepare_narration_review)."""
from __future__ import annotations

from dataclasses import dataclass

_VALID_OUTPUT_RESOLUTIONS = ("16:9", "9:16")


@dataclass
class ClipSpec:
    path: str
    trim_in: float
    trim_out: float
    script_text: str = ""
    use_llm_generation: bool = False

    def __post_init__(self) -> None:
        if self.trim_in < 0:
            raise ValueError("trim_in must be non-negative")
        if self.trim_out <= self.trim_in:
            raise ValueError("trim_out must be greater than trim_in")
        if self.use_llm_generation and self.script_text:
            raise ValueError("a clip cannot both have script_text and use_llm_generation set")
        if not self.use_llm_generation and not self.script_text:
            raise ValueError("a clip must have either script_text or use_llm_generation set")

    @property
    def duration_estimate(self) -> float:
        """Simple trim_out - trim_in arithmetic — a sizing estimate only, used
        before any physical trim exists (Layer 1). The render step measures the
        real trimmed file's duration instead (see clipstory_assembly)."""
        return self.trim_out - self.trim_in


@dataclass
class ClipStoryConfig:
    topic: str
    clips: list[ClipSpec]
    output_resolution: str = "16:9"
    tts_provider: str = ""
    tts_voice: str = ""

    def __post_init__(self) -> None:
        if not self.clips:
            raise ValueError("ClipStoryConfig requires at least one clip")
        if self.output_resolution not in _VALID_OUTPUT_RESOLUTIONS:
            raise ValueError(
                f"output_resolution must be one of {_VALID_OUTPUT_RESOLUTIONS}, "
                f"got {self.output_resolution!r}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_config.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add docu_studio/clipstory/__init__.py docu_studio/clipstory/clipstory_config.py \
        tests/unit/test_clipstory_config.py
git commit -m "feat(clipstory): add ClipSpec/ClipStoryConfig dataclasses"
```

---

### Task 3: `clipstory_pacing.py` — pure duration-fit math (Layers 2-3)

**Files:**
- Create: `docu_studio/clipstory/clipstory_pacing.py`
- Test: `tests/unit/test_clipstory_pacing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `compute_ideal_speed_factor(actual_duration: float, target_duration: float) ->
  float`; `clamp_speed_factor(ideal_factor: float, lo: float = 0.85, hi: float = 1.15) ->
  float`; `FitResult(ideal_factor: float, applied_factor: float, resulting_duration: float,
  residual_ratio: float, should_halt: bool)`; `evaluate_fit(actual_duration: float,
  target_duration: float, lo: float = 0.85, hi: float = 1.15, halt_tolerance: float = 0.10)
  -> FitResult`; `ReconciliationPlan(action: str, adjustment_seconds: float)`;
  `plan_reconciliation(actual_duration: float, target_duration: float, epsilon: float =
  0.05) -> ReconciliationPlan`. Task 5 (`clipstory_ffmpeg.apply_reconciliation`) consumes
  `ReconciliationPlan`; Task 6 (`clipstory_assembly`) consumes `evaluate_fit`/`FitResult`
  and `plan_reconciliation`/`ReconciliationPlan` directly.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for clipstory_pacing: pure duration-fit math, no I/O."""
from __future__ import annotations

import pytest

from docu_studio.clipstory.clipstory_pacing import (
    clamp_speed_factor,
    compute_ideal_speed_factor,
    evaluate_fit,
    plan_reconciliation,
)


class TestComputeIdealSpeedFactor:
    def test_normal_case(self) -> None:
        assert compute_ideal_speed_factor(actual_duration=15.0, target_duration=10.0) == pytest.approx(1.5)

    def test_actual_equals_target(self) -> None:
        assert compute_ideal_speed_factor(actual_duration=10.0, target_duration=10.0) == pytest.approx(1.0)

    def test_zero_target_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="target_duration"):
            compute_ideal_speed_factor(actual_duration=10.0, target_duration=0.0)

    def test_zero_actual_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="actual_duration"):
            compute_ideal_speed_factor(actual_duration=0.0, target_duration=10.0)


class TestClampSpeedFactor:
    def test_below_lower_bound_clamps_up(self) -> None:
        assert clamp_speed_factor(0.5) == 0.85

    def test_above_upper_bound_clamps_down(self) -> None:
        assert clamp_speed_factor(1.5) == 1.15

    def test_within_range_unchanged(self) -> None:
        assert clamp_speed_factor(1.0) == 1.0

    def test_exactly_at_lower_bound_unchanged(self) -> None:
        assert clamp_speed_factor(0.85) == 0.85

    def test_exactly_at_upper_bound_unchanged(self) -> None:
        assert clamp_speed_factor(1.15) == 1.15


class TestEvaluateFit:
    def test_within_bounds_no_halt_near_zero_residual(self) -> None:
        # ideal = 10.5/10.0 = 1.05, within [0.85, 1.15] -> applied == ideal,
        # resulting_duration == target exactly.
        fit = evaluate_fit(actual_duration=10.5, target_duration=10.0)
        assert fit.applied_factor == pytest.approx(fit.ideal_factor)
        assert fit.resulting_duration == pytest.approx(10.0)
        assert fit.residual_ratio == pytest.approx(0.0)
        assert fit.should_halt is False

    def test_clamped_small_residual_no_halt(self) -> None:
        # ideal = 12.0/10.0 = 1.2, clamped to 1.15 -> resulting = 12/1.15 = 10.4348
        fit = evaluate_fit(actual_duration=12.0, target_duration=10.0)
        assert fit.applied_factor == pytest.approx(1.15)
        assert fit.residual_ratio < 0.10
        assert fit.should_halt is False

    def test_clamped_large_residual_halts(self) -> None:
        # ideal = 20.0/10.0 = 2.0, clamped to 1.15 -> resulting = 20/1.15 = 17.39,
        # residual = 0.739 > 0.10
        fit = evaluate_fit(actual_duration=20.0, target_duration=10.0)
        assert fit.applied_factor == pytest.approx(1.15)
        assert fit.residual_ratio > 0.10
        assert fit.should_halt is True

    def test_residual_exactly_at_10_percent_does_not_halt(self) -> None:
        # applied factor clamped to hi=1.15; actual chosen so resulting/target - 1 == 0.10 exactly.
        # resulting = actual / 1.15 = 11.0  =>  actual = 12.65 (target = 10.0)
        fit = evaluate_fit(actual_duration=12.65, target_duration=10.0)
        assert fit.residual_ratio == pytest.approx(0.10, abs=1e-9)
        assert fit.should_halt is False


class TestPlanReconciliation:
    def test_shortfall_beyond_epsilon_pads(self) -> None:
        plan = plan_reconciliation(actual_duration=8.0, target_duration=10.0)
        assert plan.action == "pad"
        assert plan.adjustment_seconds == pytest.approx(2.0)

    def test_excess_beyond_epsilon_trims_with_fade(self) -> None:
        plan = plan_reconciliation(actual_duration=10.5, target_duration=10.0)
        assert plan.action == "trim_fade"
        assert plan.adjustment_seconds == pytest.approx(0.5)

    def test_within_epsilon_is_a_no_op(self) -> None:
        plan = plan_reconciliation(actual_duration=10.03, target_duration=10.0)
        assert plan.action == "none"
        assert plan.adjustment_seconds == pytest.approx(0.0)

    def test_exactly_at_epsilon_boundary_is_a_no_op(self) -> None:
        # diff == epsilon exactly (not > epsilon), so this must NOT trigger pad/trim.
        plan = plan_reconciliation(actual_duration=9.95, target_duration=10.0, epsilon=0.05)
        assert plan.action == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_pacing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.clipstory.clipstory_pacing'`.

- [ ] **Step 3: Write the implementation**

```python
"""Pure duration-fit math for Clip Story — no I/O, no ffmpeg calls. Layers 2-3 of
the three-layer duration-fit algorithm (Layer 1 word-count targeting lives in
clipstory_script_gen.py): Layer 2 is the bounded atempo speed factor
(evaluate_fit), Layer 3 is the halt decision (FitResult.should_halt) computed on
the residual AFTER the clamped tempo is applied — not the same question as
"did we have to clamp at all", which is why should_halt is not folded into
clamp_speed_factor's return value.

A separate concern, plan_reconciliation, handles the small remaining gap left
even when Layer 2 succeeds (should_halt is False): ffmpeg's -shortest mux flag
is only safe to truncate the LONGER stream, so if the tempo-adjusted narration
comes out shorter than the trimmed video, it must be padded with silence rather
than left to -shortest (which would wrongly truncate the video instead).
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LO_SPEED_FACTOR = 0.85
DEFAULT_HI_SPEED_FACTOR = 1.15
DEFAULT_HALT_TOLERANCE = 0.10
DEFAULT_RECONCILE_EPSILON = 0.05


def compute_ideal_speed_factor(actual_duration: float, target_duration: float) -> float:
    """Return the atempo factor that would land *actual_duration* exactly on
    *target_duration* (ffmpeg atempo semantics: resulting = input / tempo)."""
    if target_duration <= 0:
        raise ValueError("target_duration must be positive")
    if actual_duration <= 0:
        raise ValueError("actual_duration must be positive")
    return actual_duration / target_duration


def clamp_speed_factor(
    ideal_factor: float,
    lo: float = DEFAULT_LO_SPEED_FACTOR,
    hi: float = DEFAULT_HI_SPEED_FACTOR,
) -> float:
    return max(lo, min(hi, ideal_factor))


@dataclass(frozen=True)
class FitResult:
    ideal_factor: float
    applied_factor: float
    resulting_duration: float
    residual_ratio: float
    should_halt: bool


def evaluate_fit(
    actual_duration: float,
    target_duration: float,
    lo: float = DEFAULT_LO_SPEED_FACTOR,
    hi: float = DEFAULT_HI_SPEED_FACTOR,
    halt_tolerance: float = DEFAULT_HALT_TOLERANCE,
) -> FitResult:
    ideal_factor = compute_ideal_speed_factor(actual_duration, target_duration)
    applied_factor = clamp_speed_factor(ideal_factor, lo, hi)
    resulting_duration = actual_duration / applied_factor
    residual_ratio = abs(resulting_duration - target_duration) / target_duration
    should_halt = residual_ratio > halt_tolerance
    return FitResult(
        ideal_factor=ideal_factor,
        applied_factor=applied_factor,
        resulting_duration=resulting_duration,
        residual_ratio=residual_ratio,
        should_halt=should_halt,
    )


@dataclass(frozen=True)
class ReconciliationPlan:
    action: str  # "pad" | "trim_fade" | "none"
    adjustment_seconds: float


def plan_reconciliation(
    actual_duration: float,
    target_duration: float,
    epsilon: float = DEFAULT_RECONCILE_EPSILON,
) -> ReconciliationPlan:
    diff = target_duration - actual_duration
    if diff > epsilon:
        return ReconciliationPlan(action="pad", adjustment_seconds=diff)
    if diff < -epsilon:
        return ReconciliationPlan(action="trim_fade", adjustment_seconds=-diff)
    return ReconciliationPlan(action="none", adjustment_seconds=0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_pacing.py -v`
Expected: PASS (16 tests).

- [ ] **Step 5: Commit**

```bash
git add docu_studio/clipstory/clipstory_pacing.py tests/unit/test_clipstory_pacing.py
git commit -m "feat(clipstory): add three-layer duration-fit pure math"
```

---

### Task 4: `clipstory_script_gen.py` — Layer 1 word targeting + coordinated LLM call

**Files:**
- Create: `docu_studio/clipstory/clipstory_script_gen.py`
- Test: `tests/unit/test_clipstory_script_gen.py`

**Interfaces:**
- Consumes: `get_wpm` from `docu_studio.common.tts_calibration` (Task 1);
  `docu_studio.adapters.llm.base.LLMProvider` (`generate_script(topic: str, target_words:
  int, on_diminishing_returns=None) -> str`); `ClipSpec` from
  `docu_studio.clipstory.clipstory_config` (Task 2).
- Produces: `target_word_count(duration_seconds: float, wpm: float = 170) -> int`;
  `estimated_seconds(word_count: int, wpm: float = 170) -> float`; `count_words(text: str)
  -> int`; `SegmentPlan(index: int, fixed_text: str | None, target_words: int)`;
  `build_coordinated_prompt(topic: str, segments: list[SegmentPlan]) -> str`;
  `parse_coordinated_response(response: str, expected_count: int) -> dict[int, str] |
  None`; `generate_coordinated_narration(topic: str, segments: list[SegmentPlan], llm:
  LLMProvider) -> dict[int, str]` (raises `RuntimeError` after 2 failed parse attempts);
  `prepare_narration_review(topic: str, clips: list[ClipSpec], llm: LLMProvider, wpm:
  float) -> dict[int, dict]` (each value: `{"text": str, "pace_estimate_seconds": float}`).
  Task 8 (`bridge.generate_clipstory_narration`) calls `prepare_narration_review` directly.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for clipstory_script_gen: Layer 1 word targeting + coordinated LLM call."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docu_studio.clipstory.clipstory_config import ClipSpec
from docu_studio.clipstory.clipstory_script_gen import (
    SegmentPlan,
    build_coordinated_prompt,
    count_words,
    estimated_seconds,
    generate_coordinated_narration,
    parse_coordinated_response,
    prepare_narration_review,
    target_word_count,
)


class TestTargetWordCount:
    def test_known_wpm_and_duration(self) -> None:
        assert target_word_count(duration_seconds=60.0, wpm=170) == 170

    def test_rounds_to_nearest_word(self) -> None:
        assert target_word_count(duration_seconds=10.0, wpm=170) == 28  # 28.33 -> 28

    def test_default_wpm_is_170(self) -> None:
        assert target_word_count(duration_seconds=60.0) == 170


class TestEstimatedSeconds:
    def test_known_word_count_and_wpm(self) -> None:
        assert estimated_seconds(word_count=170, wpm=170) == pytest.approx(60.0)

    def test_zero_words_is_zero_seconds(self) -> None:
        assert estimated_seconds(word_count=0, wpm=170) == pytest.approx(0.0)


class TestCountWords:
    def test_simple_sentence(self) -> None:
        assert count_words("Hello there, world.") == 3

    def test_collapses_whitespace(self) -> None:
        assert count_words("  one   two \n three  ") == 3

    def test_empty_string_is_zero(self) -> None:
        assert count_words("") == 0


class TestParseCoordinatedResponse:
    def test_well_formed_response_parses_all_segments(self) -> None:
        response = (
            "===SEGMENT 0===\nFirst clip narration.\n"
            "===SEGMENT 1===\nSecond clip narration.\n"
        )
        result = parse_coordinated_response(response, expected_count=2)
        assert result == {0: "First clip narration.", 1: "Second clip narration."}

    def test_missing_delimiter_returns_none(self) -> None:
        response = "Just some narration text with no markers at all."
        assert parse_coordinated_response(response, expected_count=2) is None

    def test_wrong_segment_count_returns_none(self) -> None:
        response = "===SEGMENT 0===\nOnly one segment.\n"
        assert parse_coordinated_response(response, expected_count=2) is None


class TestGenerateCoordinatedNarration:
    def test_single_call_success(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = (
            "===SEGMENT 0===\nGenerated text for slot 0.\n"
        )
        segments = [SegmentPlan(index=0, fixed_text=None, target_words=10)]
        result = generate_coordinated_narration("Topic", segments, llm)
        assert result == {0: "Generated text for slot 0."}
        assert llm.generate_script.call_count == 1

    def test_retries_once_on_parse_failure_then_succeeds(self) -> None:
        llm = MagicMock()
        llm.generate_script.side_effect = [
            "no delimiters here",
            "===SEGMENT 0===\nRetried text.\n",
        ]
        segments = [SegmentPlan(index=0, fixed_text=None, target_words=10)]
        result = generate_coordinated_narration("Topic", segments, llm)
        assert result == {0: "Retried text."}
        assert llm.generate_script.call_count == 2

    def test_hard_fails_after_two_parse_failures(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "no delimiters here either time"
        segments = [SegmentPlan(index=0, fixed_text=None, target_words=10)]
        with pytest.raises(RuntimeError, match="could not parse"):
            generate_coordinated_narration("Topic", segments, llm)
        assert llm.generate_script.call_count == 2

    def test_only_returns_flagged_slots_not_fixed_ones(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = (
            "===SEGMENT 0===\nFixed text repeated verbatim.\n"
            "===SEGMENT 1===\nNewly generated text.\n"
        )
        segments = [
            SegmentPlan(index=0, fixed_text="Fixed text repeated verbatim.", target_words=0),
            SegmentPlan(index=1, fixed_text=None, target_words=10),
        ]
        result = generate_coordinated_narration("Topic", segments, llm)
        assert result == {1: "Newly generated text."}


class TestPrepareNarrationReview:
    def test_user_written_clip_gets_pace_estimate_no_llm_call(self) -> None:
        llm = MagicMock()
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="One two three four five.")]
        review = prepare_narration_review("Topic", clips, llm, wpm=170.0)
        assert review[0]["text"] == "One two three four five."
        assert review[0]["pace_estimate_seconds"] == pytest.approx(estimated_seconds(5, 170.0))
        llm.generate_script.assert_not_called()

    def test_llm_flagged_clip_gets_generated_text(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "===SEGMENT 0===\nGenerated narration text here.\n"
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, use_llm_generation=True)]
        review = prepare_narration_review("Topic", clips, llm, wpm=170.0)
        assert review[0]["text"] == "Generated narration text here."
        llm.generate_script.assert_called_once()

    def test_mixed_sequence_calls_llm_once_for_all_flagged_clips(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = (
            "===SEGMENT 0===\nUser wrote this.\n"
            "===SEGMENT 1===\nGenerated for slot 1.\n"
        )
        clips = [
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=5.0, script_text="User wrote this."),
            ClipSpec(path="/b.mp4", trim_in=0.0, trim_out=8.0, use_llm_generation=True),
        ]
        review = prepare_narration_review("Topic", clips, llm, wpm=170.0)
        assert review[0]["text"] == "User wrote this."
        assert review[1]["text"] == "Generated for slot 1."
        assert llm.generate_script.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_script_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.clipstory.clipstory_script_gen'`.

- [ ] **Step 3: Write the implementation**

```python
"""Layer 1 of the duration-fit algorithm: word-count targeting from duration, plus
the one coordinated LLM call for all use_llm_generation=True clips in a sequence,
given the full sequence (including fixed user-written text as context) so the
narration reads continuously across cuts. See docs/superpowers/specs/
2026-07-13-clipstory-phase1-design.md for the full rationale.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.clipstory.clipstory_config import ClipSpec
from docu_studio.common.tts_calibration import get_wpm

_log = logging.getLogger(__name__)

CLIPSTORY_DEFAULT_WPM = 170
_SEGMENT_DELIMITER_RE = re.compile(r"===SEGMENT (\d+)===")


def target_word_count(duration_seconds: float, wpm: float = CLIPSTORY_DEFAULT_WPM) -> int:
    return round(duration_seconds / 60 * wpm)


def estimated_seconds(word_count: int, wpm: float = CLIPSTORY_DEFAULT_WPM) -> float:
    return word_count / wpm * 60


def count_words(text: str) -> int:
    return len(text.split())


@dataclass(frozen=True)
class SegmentPlan:
    index: int
    fixed_text: str | None  # None means: this slot needs LLM generation
    target_words: int


def build_coordinated_prompt(topic: str, segments: list[SegmentPlan]) -> str:
    lines = [
        f"You are writing narration for a multi-clip video about: {topic}",
        "",
        "The video is made of the following ordered clips. Some already have fixed "
        "narration text that you must NOT change — treat it as context establishing "
        "continuity. Others need you to write new narration that continues naturally "
        "from the surrounding fixed text.",
        "",
    ]
    for seg in segments:
        if seg.fixed_text is not None:
            lines.append(f"Clip {seg.index}: FIXED TEXT (repeat verbatim) — \"{seg.fixed_text}\"")
        else:
            lines.append(
                f"Clip {seg.index}: WRITE NEW NARRATION — target approximately "
                f"{seg.target_words} words."
            )
    lines += [
        "",
        "OUTPUT FORMAT (mandatory):",
        "For every clip listed above, in order, output a line of the exact form "
        "'===SEGMENT n===' (where n is that clip's number) immediately followed by "
        "its narration text — for FIXED TEXT clips, repeat the fixed text verbatim; "
        "for WRITE NEW NARRATION clips, write the new narration there.",
        "Plain spoken text only. No markdown, no headers, no bullet points, no "
        "quotation marks around the text.",
        "Write only the segments in the format above — nothing else.",
    ]
    return "\n".join(lines)


def parse_coordinated_response(response: str, expected_count: int) -> dict[int, str] | None:
    """Split *response* by '===SEGMENT n===' markers. Returns {index: text} only if
    exactly *expected_count* segments were found — never guess-splits a partial match."""
    matches = list(_SEGMENT_DELIMITER_RE.finditer(response))
    if len(matches) != expected_count:
        _log.warning(
            "Clip Story coordinated response segment count mismatch: got %d, expected %d",
            len(matches), expected_count,
        )
        return None
    result: dict[int, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(response)
        result[int(m.group(1))] = response[start:end].strip()
    return result


def generate_coordinated_narration(
    topic: str, segments: list[SegmentPlan], llm: LLMProvider
) -> dict[int, str]:
    """Run the one coordinated LLM call for all *segments* with fixed_text=None,
    returning {index: generated_text} for those slots only. One retry on a parse
    mismatch, then a hard RuntimeError — never guess-splits."""
    prompt = build_coordinated_prompt(topic, segments)
    total_target_words = sum(seg.target_words for seg in segments if seg.fixed_text is None)

    response = llm.generate_script(topic=prompt, target_words=total_target_words)
    parsed = parse_coordinated_response(response, len(segments))
    if parsed is None:
        _log.info("Clip Story coordinated narration parse failed, retrying once")
        response = llm.generate_script(topic=prompt, target_words=total_target_words)
        parsed = parse_coordinated_response(response, len(segments))
    if parsed is None:
        raise RuntimeError(
            f"Clip Story coordinated narration generation failed: could not parse "
            f"{len(segments)} segments from the LLM response after 2 attempts."
        )
    return {seg.index: parsed[seg.index] for seg in segments if seg.fixed_text is None}


def prepare_narration_review(
    topic: str, clips: list[ClipSpec], llm: LLMProvider, wpm: float
) -> dict[int, dict]:
    """Layer 1 review-step orchestration: target word counts from each clip's
    trim-arithmetic duration estimate, one coordinated LLM call for flagged clips,
    and a pace estimate for every clip's final text — everything the GUI needs to
    show before any TTS/ffmpeg work runs."""
    segments = [
        SegmentPlan(
            index=i,
            fixed_text=None if clip.use_llm_generation else clip.script_text,
            target_words=target_word_count(clip.duration_estimate, wpm),
        )
        for i, clip in enumerate(clips)
    ]
    generated: dict[int, str] = {}
    if any(seg.fixed_text is None for seg in segments):
        generated = generate_coordinated_narration(topic, segments, llm)

    review: dict[int, dict] = {}
    for i, clip in enumerate(clips):
        text = generated.get(i, clip.script_text)
        review[i] = {
            "text": text,
            "pace_estimate_seconds": estimated_seconds(count_words(text), wpm),
        }
    return review
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_script_gen.py -v`
Expected: PASS (16 tests).

- [ ] **Step 5: Commit**

```bash
git add docu_studio/clipstory/clipstory_script_gen.py tests/unit/test_clipstory_script_gen.py
git commit -m "feat(clipstory): add Layer 1 word targeting and coordinated LLM narration"
```

---

### Task 5: `clipstory_ffmpeg.py` — `ClipStoryFFmpeg` class

**Files:**
- Create: `docu_studio/clipstory/clipstory_ffmpeg.py`
- Test: `tests/unit/test_clipstory_ffmpeg.py`

**Interfaces:**
- Consumes: `FFmpegWrapper` (`docu_studio.media.ffmpeg_wrapper`) — inherits `get_duration`,
  `trim_clip`, `concat_scenes`, `mux_audio_video`, `_check`, `self._ffmpeg`/`self._ffprobe`
  unchanged; `finalize_filter` from `docu_studio.common.ffmpeg_finalize`;
  `ReconciliationPlan` from `docu_studio.clipstory.clipstory_pacing` (Task 3).
- Produces: `class ClipStoryFFmpeg(FFmpegWrapper)` with `normalize_clip(input_path: str,
  output_resolution: str, output_path: str) -> None`; `apply_atempo(input_path: str,
  speed_factor: float, output_path: str) -> None`; `apply_reconciliation(input_path: str,
  plan: ReconciliationPlan, target_duration: float, output_path: str, fade_duration: float
  = 0.3) -> None`; `extract_poster_frame(video_path: str, timestamp: float, output_path:
  str) -> None`. Task 6 (`clipstory_assembly`) calls all four; Task 8
  (`bridge.browse_videos` clip-metadata step) calls `extract_poster_frame` and inherited
  `get_duration`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for ClipStoryFFmpeg — subprocess mocked, no real ffmpeg execution."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docu_studio.clipstory.clipstory_ffmpeg import ClipStoryFFmpeg
from docu_studio.clipstory.clipstory_pacing import ReconciliationPlan
from docu_studio.media.ffmpeg_wrapper import FFmpegError


@pytest.fixture
def wrapper() -> ClipStoryFFmpeg:
    with patch("docu_studio.media.ffmpeg_wrapper.imageio_ffmpeg") as mock_ffmpeg_mod:
        mock_ffmpeg_mod.get_ffmpeg_exe.return_value = "/fake/ffmpeg"
        with patch("docu_studio.media.ffmpeg_wrapper.platform_layer") as mock_pl:
            mock_pl.ffprobe_exe.return_value = "/fake/ffprobe"
            return ClipStoryFFmpeg()


class TestNormalizeClip:
    def test_16_9_uses_1920x1080_scale_pad(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.normalize_clip("/in.mp4", "16:9", "/out.mp4")
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert "scale=1920:1080" in vf
        assert "pad=1920:1080" in vf
        assert "setsar=1,format=yuv420p" in vf

    def test_9_16_uses_1080x1920_scale_pad(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.normalize_clip("/in.mp4", "9:16", "/out.mp4")
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert "scale=1080:1920" in vf
        assert "pad=1080:1920" in vf

    def test_unknown_resolution_raises(self, wrapper: ClipStoryFFmpeg) -> None:
        with pytest.raises(ValueError, match="output_resolution"):
            wrapper.normalize_clip("/in.mp4", "4:3", "/out.mp4")

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.normalize_clip("/in.mp4", "16:9", "/out.mp4")


class TestApplyAtempo:
    def test_atempo_filter_includes_speed_factor(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_atempo("/in.mp3", 1.1, "/out.mp3")
        args = mock_run.call_args[0][0]
        af = args[args.index("-filter:a") + 1]
        assert af == "atempo=1.1"


class TestApplyReconciliation:
    def test_pad_action_uses_apad_filter(self, wrapper: ClipStoryFFmpeg) -> None:
        plan = ReconciliationPlan(action="pad", adjustment_seconds=2.0)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_reconciliation("/in.mp3", plan, target_duration=10.0, output_path="/out.mp3")
        args = mock_run.call_args[0][0]
        af = args[args.index("-af") + 1]
        assert "apad=pad_dur=2.0" in af

    def test_trim_fade_action_uses_atrim_and_afade(self, wrapper: ClipStoryFFmpeg) -> None:
        plan = ReconciliationPlan(action="trim_fade", adjustment_seconds=0.5)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_reconciliation("/in.mp3", plan, target_duration=10.0, output_path="/out.mp3")
        args = mock_run.call_args[0][0]
        af = args[args.index("-af") + 1]
        assert "atrim=0:10.0" in af
        assert "afade=t=out" in af

    def test_none_action_copies_file(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        src = tmp_path / "in.mp3"
        src.write_bytes(b"fake audio data")
        dst = tmp_path / "out.mp3"
        plan = ReconciliationPlan(action="none", adjustment_seconds=0.0)
        wrapper.apply_reconciliation(str(src), plan, target_duration=10.0, output_path=str(dst))
        assert dst.read_bytes() == b"fake audio data"


class TestExtractPosterFrame:
    def test_extracts_single_frame_at_timestamp(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.extract_poster_frame("/in.mp4", 1.5, "/out.jpg")
        args = mock_run.call_args[0][0]
        assert "-ss" in args
        assert args[args.index("-ss") + 1] == "1.5"
        assert "-frames:v" in args
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_ffmpeg.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.clipstory.clipstory_ffmpeg'`.

- [ ] **Step 3: Write the implementation**

```python
"""ClipStoryFFmpeg: adds atempo pacing, per-clip resolution normalization, audio
reconciliation (pad/trim-fade), and poster-frame extraction on top of the shared
FFmpegWrapper. Every clip is normalized before mux/concat because uploaded videos
arrive in far more heterogeneous encodings than Shorts/Slideshow's stock footage —
see docs/superpowers/specs/2026-07-13-clipstory-phase1-design.md.
"""
from __future__ import annotations

import shutil
import subprocess

from docu_studio.clipstory.clipstory_pacing import ReconciliationPlan
from docu_studio.common.ffmpeg_finalize import finalize_filter
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_OUTPUT_RESOLUTIONS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}


class ClipStoryFFmpeg(FFmpegWrapper):
    def normalize_clip(self, input_path: str, output_resolution: str, output_path: str) -> None:
        if output_resolution not in _OUTPUT_RESOLUTIONS:
            raise ValueError(f"Unknown output_resolution: {output_resolution!r}")
        w, h = _OUTPUT_RESOLUTIONS[output_resolution]
        vf = finalize_filter(
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        result = subprocess.run(
            [self._ffmpeg, "-y", "-i", input_path, "-vf", vf,
             "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-an", output_path],
            capture_output=True, text=True,
        )
        self._check(result, f"normalize_clip → {output_path!r}")

    def apply_atempo(self, input_path: str, speed_factor: float, output_path: str) -> None:
        result = subprocess.run(
            [self._ffmpeg, "-y", "-i", input_path,
             "-filter:a", f"atempo={speed_factor}", "-vn", output_path],
            capture_output=True, text=True,
        )
        self._check(result, f"apply_atempo → {output_path!r}")

    def apply_reconciliation(
        self,
        input_path: str,
        plan: ReconciliationPlan,
        target_duration: float,
        output_path: str,
        fade_duration: float = 0.3,
    ) -> None:
        if plan.action == "pad":
            af = f"apad=pad_dur={plan.adjustment_seconds}"
            result = subprocess.run(
                [self._ffmpeg, "-y", "-i", input_path, "-af", af, output_path],
                capture_output=True, text=True,
            )
            self._check(result, f"apply_reconciliation(pad) → {output_path!r}")
        elif plan.action == "trim_fade":
            fade_start = max(0.0, target_duration - fade_duration)
            af = f"atrim=0:{target_duration},afade=t=out:st={fade_start}:d={fade_duration}"
            result = subprocess.run(
                [self._ffmpeg, "-y", "-i", input_path, "-af", af, output_path],
                capture_output=True, text=True,
            )
            self._check(result, f"apply_reconciliation(trim_fade) → {output_path!r}")
        else:
            shutil.copy(input_path, output_path)

    def extract_poster_frame(self, video_path: str, timestamp: float, output_path: str) -> None:
        result = subprocess.run(
            [self._ffmpeg, "-y", "-ss", str(timestamp), "-i", video_path,
             "-frames:v", "1", "-q:v", "3", output_path],
            capture_output=True, text=True,
        )
        self._check(result, f"extract_poster_frame → {output_path!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_ffmpeg.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add docu_studio/clipstory/clipstory_ffmpeg.py tests/unit/test_clipstory_ffmpeg.py
git commit -m "feat(clipstory): add ClipStoryFFmpeg (atempo, normalize, reconciliation, poster frame)"
```

---

### Task 6: `clipstory_assembly.py` — per-clip pipeline + concat orchestration

**Files:**
- Create: `docu_studio/clipstory/clipstory_assembly.py`
- Test: `tests/unit/test_clipstory_assembly.py`

**Interfaces:**
- Consumes: `ClipStoryConfig`/`ClipSpec` (Task 2); `evaluate_fit`, `plan_reconciliation`
  (Task 3); `ClipStoryFFmpeg` (Task 5); `docu_studio.adapters.tts.base.TTSProvider`
  (`synthesize(text: str, output_path: str) -> float`).
- Produces: `class ClipStoryFitError(Exception)` (message carries the full per-clip
  numeric report); `assemble_clip_story(config: ClipStoryConfig, tts: TTSProvider,
  work_dir: Path, output_path: Path, cancel_event: threading.Event | None = None) -> None`.
  Task 7 (`ClipStoryRunner._execute`) calls `assemble_clip_story` and catches
  `ClipStoryFitError`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for clipstory_assembly — ffmpeg and TTS mocked, no real I/O."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.clipstory.clipstory_assembly import ClipStoryFitError, assemble_clip_story
from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig


def _make_config(clips=None) -> ClipStoryConfig:
    clips = clips or [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hello there world.")]
    return ClipStoryConfig(topic="Test", clips=clips)


@pytest.fixture
def mock_ffmpeg():
    with patch("docu_studio.clipstory.clipstory_assembly.ClipStoryFFmpeg") as MockCls:
        instance = MockCls.return_value
        instance.get_duration.return_value = 10.0  # trimmed video == target duration
        yield instance


class TestAssembleClipStoryHappyPath:
    def test_single_clip_within_bounds_no_halt(self, mock_ffmpeg, tmp_path: Path) -> None:
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 10.0]  # trimmed, tempo-audio, (unused 3rd guard)
        tts = MagicMock()
        tts.synthesize.return_value = 10.2  # actual narration duration, close to target
        config = _make_config()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.trim_clip.assert_called_once()
        mock_ffmpeg.normalize_clip.assert_called_once()
        mock_ffmpeg.apply_atempo.assert_called_once()
        mock_ffmpeg.mux_audio_video.assert_called_once()
        mock_ffmpeg.concat_scenes.assert_called_once()

    def test_multiple_clips_all_processed_in_order(self, mock_ffmpeg, tmp_path: Path) -> None:
        clips = [
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="First clip narration text."),
            ClipSpec(path="/b.mp4", trim_in=0.0, trim_out=8.0, script_text="Second clip narration text."),
        ]
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 8.0, 8.0]
        tts = MagicMock()
        tts.synthesize.side_effect = [10.0, 8.0]
        config = _make_config(clips)
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        assert mock_ffmpeg.trim_clip.call_count == 2
        assert mock_ffmpeg.mux_audio_video.call_count == 2
        concat_args = mock_ffmpeg.concat_scenes.call_args[0][0]
        assert len(concat_args) == 2


class TestAssembleClipStoryLayer3Halt:
    def test_halts_with_numeric_report_when_gap_too_large(self, mock_ffmpeg, tmp_path: Path) -> None:
        mock_ffmpeg.get_duration.return_value = 10.0  # trimmed target duration
        tts = MagicMock()
        tts.synthesize.return_value = 30.0  # wildly over target -> forces halt
        config = _make_config()
        with pytest.raises(ClipStoryFitError, match="target=10.00s"):
            assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.apply_atempo.assert_not_called()
        mock_ffmpeg.concat_scenes.assert_not_called()


class TestAssembleClipStoryReconciliation:
    def test_short_narration_gets_padded_before_mux(self, mock_ffmpeg, tmp_path: Path) -> None:
        # trimmed=10.0, raw narration actual=9.0 (within [0.85,1.15] ideal factor 0.9,
        # applied unclamped -> resulting exactly 10.0) then reconciliation get_duration
        # call reports a slightly-short post-atempo duration to force the pad branch.
        mock_ffmpeg.get_duration.side_effect = [10.0, 9.8]
        tts = MagicMock()
        tts.synthesize.return_value = 9.0
        config = _make_config()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.apply_reconciliation.assert_called_once()
        plan = mock_ffmpeg.apply_reconciliation.call_args[0][1]
        assert plan.action == "pad"


class TestAssembleClipStoryCancellation:
    def test_cancel_event_set_before_any_clip_stops_immediately(self, mock_ffmpeg, tmp_path: Path) -> None:
        tts = MagicMock()
        config = _make_config()
        cancel_event = threading.Event()
        cancel_event.set()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4", cancel_event=cancel_event)
        mock_ffmpeg.trim_clip.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_assembly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.clipstory.clipstory_assembly'`.

- [ ] **Step 3: Write the implementation**

```python
"""Per-clip Clip Story render pipeline: trim -> measure real duration -> normalize
-> TTS -> Layer 2/3 fit -> reconciliation -> mux -> (all clips) hard-cut concat.
See docs/superpowers/specs/2026-07-13-clipstory-phase1-design.md for the full
per-clip pipeline and the rationale for measuring the trimmed file's real
duration rather than trusting trim_out - trim_in arithmetic.
"""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.clipstory.clipstory_config import ClipStoryConfig
from docu_studio.clipstory.clipstory_ffmpeg import ClipStoryFFmpeg
from docu_studio.clipstory.clipstory_pacing import evaluate_fit, plan_reconciliation

_log = logging.getLogger(__name__)


class ClipStoryFitError(Exception):
    """Raised when Layer 3 halts the render — the exception message carries the
    full per-clip numeric report (target/actual/factors/residual) for every clip
    processed so far, so the GUI's existing error-display surfaces real numbers."""


def assemble_clip_story(
    config: ClipStoryConfig,
    tts: TTSProvider,
    work_dir: Path,
    output_path: Path,
    cancel_event: Event | None = None,
) -> None:
    ffmpeg = ClipStoryFFmpeg()
    segment_paths: list[str] = []
    report_lines: list[str] = []

    for i, clip in enumerate(config.clips):
        if cancel_event is not None and cancel_event.is_set():
            return

        trimmed_path = str(work_dir / f"clip_{i}_trimmed.mp4")
        ffmpeg.trim_clip(clip.path, clip.trim_in, clip.trim_out - clip.trim_in, trimmed_path)
        # Measured, not trim_out - trim_in arithmetic: ffmpeg trims aren't always
        # frame-exact, and this value is authoritative for everything below.
        measured_target_duration = ffmpeg.get_duration(trimmed_path)

        normalized_path = str(work_dir / f"clip_{i}_normalized.mp4")
        ffmpeg.normalize_clip(trimmed_path, config.output_resolution, normalized_path)

        raw_narration_path = str(work_dir / f"clip_{i}_narration_raw.mp3")
        actual_duration = tts.synthesize(clip.script_text, raw_narration_path)

        fit = evaluate_fit(actual_duration, measured_target_duration)
        report_line = (
            f"Clip {i} ({Path(clip.path).name}): target={measured_target_duration:.2f}s "
            f"actual={actual_duration:.2f}s ideal_factor={fit.ideal_factor:.3f} "
            f"applied_factor={fit.applied_factor:.3f} resulting={fit.resulting_duration:.2f}s "
            f"residual={fit.residual_ratio * 100:.1f}%"
        )
        report_lines.append(report_line)
        _log.info(report_line)
        if fit.should_halt:
            raise ClipStoryFitError(
                "Clip Story render halted: narration pacing gap too large to fix "
                "automatically.\n" + "\n".join(report_lines)
            )

        tempo_path = str(work_dir / f"clip_{i}_narration_tempo.mp3")
        ffmpeg.apply_atempo(raw_narration_path, fit.applied_factor, tempo_path)

        post_tempo_duration = ffmpeg.get_duration(tempo_path)
        plan = plan_reconciliation(post_tempo_duration, measured_target_duration)
        final_narration_path = str(work_dir / f"clip_{i}_narration_final.mp3")
        ffmpeg.apply_reconciliation(
            tempo_path, plan, measured_target_duration, final_narration_path
        )
        _log.info(
            "Clip %d reconciliation: action=%s adjustment=%.3fs",
            i, plan.action, plan.adjustment_seconds,
        )

        segment_path = str(work_dir / f"clip_{i}_segment.mp4")
        ffmpeg.mux_audio_video(normalized_path, final_narration_path, segment_path)
        segment_paths.append(segment_path)

    if cancel_event is not None and cancel_event.is_set():
        return

    # Segments are already uniform resolution/SAR/pixfmt (normalize_clip) and
    # already have narration muxed in — concat_scenes just hard-cuts them together.
    ffmpeg.concat_scenes(segment_paths, str(output_path))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_assembly.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add docu_studio/clipstory/clipstory_assembly.py tests/unit/test_clipstory_assembly.py
git commit -m "feat(clipstory): add per-clip assembly orchestration with Layer 2/3 fit"
```

---

### Task 7: `clipstory_runner.py` — `ClipStoryRunner` thread

**Files:**
- Create: `docu_studio/clipstory/clipstory_runner.py`
- Test: `tests/unit/test_clipstory_runner.py`

**Interfaces:**
- Consumes: `assemble_clip_story`, `ClipStoryFitError` (Task 6); `ClipStoryConfig` (Task 2);
  `create_project_folder(topic: str, ts: datetime, base: Path) -> Path` from
  `docu_studio.output.project_folder`; `RunRecord`/`save_run` from
  `docu_studio.history.run_history`; `ProgressEvent`/`ErrorEvent` from
  `docu_studio.pipeline.events`.
- Produces: `class ClipStoryRunner(threading.Thread)` with `__init__(config:
  ClipStoryConfig, tts: TTSProvider, output_base: Path)`, `.event_queue: queue.Queue`,
  `.cancel_event: threading.Event`, `._project_folder: Path | None`,
  `._final_video_path: Path | None`, `.run() -> None` — same attribute shape as
  `ShortsRunner` so `Bridge._translate_events`/`_to_js_event` work unmodified. Task 8
  (`bridge.start_clipstory_run`) instantiates and starts this.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for ClipStoryRunner — assembly and history save mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from docu_studio.clipstory.clipstory_assembly import ClipStoryFitError
from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig
from docu_studio.clipstory.clipstory_runner import ClipStoryRunner, ClipStoryRunStatus
from docu_studio.pipeline.events import ErrorEvent, ProgressEvent


def _make_config() -> ClipStoryConfig:
    clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hello world.")]
    return ClipStoryConfig(topic="Test", clips=clips)


class TestClipStoryRunnerHappyPath:
    def test_successful_run_marks_completed_and_pushes_done_event(self, tmp_path: Path) -> None:
        with patch("docu_studio.clipstory.clipstory_runner.create_project_folder") as mock_create, \
             patch("docu_studio.clipstory.clipstory_runner.assemble_clip_story") as mock_assemble, \
             patch("docu_studio.clipstory.clipstory_runner.save_run"):
            mock_create.return_value = tmp_path
            runner = ClipStoryRunner(config=_make_config(), tts=MagicMock(), output_base=tmp_path)
            runner.run()
        assert runner._status == ClipStoryRunStatus.COMPLETED
        assert runner._final_video_path == tmp_path / "clipstory_final.mp4"
        mock_assemble.assert_called_once()
        events = []
        while True:
            ev = runner.event_queue.get_nowait()
            if ev is None:
                break
            events.append(ev)
        assert any(isinstance(e, ProgressEvent) and e.stage == "Done" for e in events)


class TestClipStoryRunnerFitHalt:
    def test_fit_error_pushes_error_event_and_marks_failed(self, tmp_path: Path) -> None:
        with patch("docu_studio.clipstory.clipstory_runner.create_project_folder") as mock_create, \
             patch("docu_studio.clipstory.clipstory_runner.assemble_clip_story") as mock_assemble, \
             patch("docu_studio.clipstory.clipstory_runner.save_run"):
            mock_create.return_value = tmp_path
            mock_assemble.side_effect = ClipStoryFitError("Clip 0: target=10.00s actual=30.00s ...")
            runner = ClipStoryRunner(config=_make_config(), tts=MagicMock(), output_base=tmp_path)
            runner.run()
        assert runner._status == ClipStoryRunStatus.FAILED
        events = []
        while True:
            ev = runner.event_queue.get_nowait()
            if ev is None:
                break
            events.append(ev)
        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1
        assert "target=10.00s" in error_events[0].message


class TestClipStoryRunnerCancellation:
    def test_cancel_before_execute_skips_assembly(self, tmp_path: Path) -> None:
        with patch("docu_studio.clipstory.clipstory_runner.create_project_folder") as mock_create, \
             patch("docu_studio.clipstory.clipstory_runner.assemble_clip_story") as mock_assemble, \
             patch("docu_studio.clipstory.clipstory_runner.save_run"):
            mock_create.return_value = tmp_path
            runner = ClipStoryRunner(config=_make_config(), tts=MagicMock(), output_base=tmp_path)
            runner.cancel_event.set()
            runner.run()
        assert runner._status == ClipStoryRunStatus.CANCELLED
        mock_assemble.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.clipstory.clipstory_runner'`.

- [ ] **Step 3: Write the implementation**

```python
"""ClipStoryRunner: threading.Thread orchestrator mirroring ShortsRunner's shape
(event_queue, cancel_event, _project_folder, _final_video_path) so Bridge's
existing event-translation code works unmodified for the new 'clipstory' mode.
"""
from __future__ import annotations

import logging
import queue
import tempfile
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.clipstory.clipstory_assembly import ClipStoryFitError, assemble_clip_story
from docu_studio.clipstory.clipstory_config import ClipStoryConfig
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, ProgressEvent

_log = logging.getLogger(__name__)


class ClipStoryRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ClipStoryRunner(threading.Thread):
    def __init__(self, config: ClipStoryConfig, tts: TTSProvider, output_base: Path) -> None:
        super().__init__(daemon=True, name="ClipStoryRunner")
        self.config = config
        self.tts = tts
        self.output_base = output_base
        self.event_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self._status = ClipStoryRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        try:
            self._execute()
        except ClipStoryFitError as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
        finally:
            self._save_history()
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        self._project_folder = create_project_folder(
            self.config.topic, self._started_at, self.output_base
        )
        self.event_queue.put(ProgressEvent(stage="ClipStory Assembly", message="Assembling clips…"))
        with tempfile.TemporaryDirectory(prefix="docu_studio_clipstory_") as tmp:
            if self._cancelled():
                return
            output_path = self._project_folder / "clipstory_final.mp4"
            assemble_clip_story(
                self.config, self.tts, Path(tmp), output_path, cancel_event=self.cancel_event
            )
            if self._cancelled():
                return
            self._final_video_path = output_path
        self._status = ClipStoryRunStatus.COMPLETED
        self.event_queue.put(ProgressEvent(stage="Done", message="Clip Story completed."))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = ClipStoryRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            save_run(RunRecord(
                topic=self.config.topic,
                mode="clipstory",
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source="user_supplied",
                fallback_triggered=False,
            ))
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_runner.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add docu_studio/clipstory/clipstory_runner.py tests/unit/test_clipstory_runner.py
git commit -m "feat(clipstory): add ClipStoryRunner"
```

---

### Task 8: `bridge.py` wiring — `browse_videos`, `generate_clipstory_narration`, `start_clipstory_run`

**Files:**
- Modify: `docu_studio/gui/bridge.py`

**Interfaces:**
- Consumes: `ClipSpec`/`ClipStoryConfig` (Task 2), `prepare_narration_review` (Task 4),
  `ClipStoryFFmpeg.extract_poster_frame`/inherited `get_duration` (Task 5),
  `ClipStoryRunner` (Task 7); existing `build_llm`, `build_tts`, `key_cache`.
- Produces: `Bridge.browse_videos() -> list[str]`; `Bridge.get_clip_metadata(paths:
  list[str]) -> dict` (per-path duration + poster-frame temp-file path, for the GUI list);
  `Bridge.generate_clipstory_narration(topic: str, clips: list[dict]) -> dict`;
  `Bridge.start_clipstory_run(config: dict) -> dict`. Task 9 (JS) calls all of these via
  `window.pywebview.api.*`.

- [ ] **Step 1: Add `_CLIPSTORY_STAGE_MAP` and extend `_FINAL_STAGE_INDEX_BY_MODE`**

In `docu_studio/gui/bridge.py`, modify the class-level maps (currently lines 29-43):
```python
    _SLIDESHOW_STAGE_MAP = {
        "tts": 0, "assembly": 1, "mux": 2, "done": 2, "complete": 2,
    }
    _CLIPSTORY_STAGE_MAP = {
        "assembly": 0, "done": 0, "complete": 0,
    }
    _FINAL_STAGE_INDEX_BY_MODE = {"doc": 7, "shorts": 6, "slideshow": 2, "clipstory": 0}
```
(Insert `_CLIPSTORY_STAGE_MAP` right after `_SLIDESHOW_STAGE_MAP`, and add the
`"clipstory": 0` entry to the existing `_FINAL_STAGE_INDEX_BY_MODE` dict literal.)

- [ ] **Step 2: Extend `_to_js_event`'s stage_map selection**

Modify the ternary chain at (currently) line 516-520 from:
```python
        stage_map = (
            self._SHORTS_STAGE_MAP if self._active_mode == "shorts"
            else self._SLIDESHOW_STAGE_MAP if self._active_mode == "slideshow"
            else self._STAGE_MAP
        )
```
to:
```python
        stage_map = (
            self._SHORTS_STAGE_MAP if self._active_mode == "shorts"
            else self._SLIDESHOW_STAGE_MAP if self._active_mode == "slideshow"
            else self._CLIPSTORY_STAGE_MAP if self._active_mode == "clipstory"
            else self._STAGE_MAP
        )
```

- [ ] **Step 3: Add `browse_videos` and `get_clip_metadata` next to `browse_images`**

Insert immediately after the existing `browse_images` method (currently ending at line 573):
```python
    def browse_videos(self) -> list[str]:
        if not self._window:
            return []
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Video Files (*.mp4;*.mov;*.mkv;*.webm;*.avi)", "All files (*.*)"),
        )
        return list(result) if result else []

    def get_clip_metadata(self, paths: list[str]) -> dict:
        try:
            import tempfile

            from docu_studio.clipstory.clipstory_ffmpeg import ClipStoryFFmpeg

            ffmpeg = ClipStoryFFmpeg()
            clips = []
            for path in paths:
                duration = ffmpeg.get_duration(path)
                poster_path = str(Path(tempfile.mkdtemp(prefix="docu_studio_clipstory_poster_")) / "poster.jpg")
                ffmpeg.extract_poster_frame(path, min(1.0, duration / 2), poster_path)
                clips.append({"path": path, "duration": duration, "poster_path": poster_path})
            return {"ok": True, "clips": clips}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Add `generate_clipstory_narration` next to `generate_slideshow_script`**

Insert immediately after the existing `generate_slideshow_script` method (currently ending
at line 442):
```python
    def generate_clipstory_narration(self, topic: str, clips: list[dict]) -> dict:
        try:
            from docu_studio.adapters.llm.factory import build_llm
            from docu_studio.clipstory.clipstory_config import ClipSpec
            from docu_studio.clipstory.clipstory_script_gen import (
                CLIPSTORY_DEFAULT_WPM,
                prepare_narration_review,
            )
            from docu_studio.common.tts_calibration import get_wpm

            s = self._settings
            provider = getattr(s, "llm_provider", "Anthropic")
            model = getattr(s, "llm_model", "claude-sonnet-4-5")
            key_map = {
                "Anthropic": key_cache.get("docu_studio_anthropic"),
                "OpenAI": key_cache.get("docu_studio_openai"),
                "OpenRouter": key_cache.get("docu_studio_openrouter"),
                "Groq": key_cache.get("docu_studio_groq"),
            }
            llm_key = key_map.get(provider, "") or ""
            llm = build_llm(provider, llm_key, model)

            tts_prov = getattr(s, "tts_provider", "elevenlabs")
            tts_voice = getattr(s, "deepgram_voice", "aura-asteria-en")
            wpm = get_wpm(tts_prov, tts_voice, default=CLIPSTORY_DEFAULT_WPM)

            clip_specs = [
                ClipSpec(
                    path=c["path"],
                    trim_in=float(c["trim_in"]),
                    trim_out=float(c["trim_out"]),
                    script_text=c.get("script_text", ""),
                    use_llm_generation=bool(c.get("use_llm_generation", False)),
                )
                for c in clips
            ]
            review = prepare_narration_review(topic, clip_specs, llm, wpm)
            return {"ok": True, "review": review}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
```

- [ ] **Step 5: Add `start_clipstory_run` next to `start_slideshow_run`**

Insert immediately after the existing `start_slideshow_run` method (currently ending at
line 396):
```python
    def start_clipstory_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "clipstory"
            from docu_studio.adapters.tts.factory import build_tts
            from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig
            from docu_studio.clipstory.clipstory_runner import ClipStoryRunner

            s = self._settings
            tts_prov = getattr(s, "tts_provider", "elevenlabs")
            tts_key = (
                key_cache.get("docu_studio_elevenlabs")
                if tts_prov == "elevenlabs"
                else key_cache.get("docu_studio_deepgram_key")
            )
            tts_voice = getattr(s, "deepgram_voice", "aura-asteria-en")
            tts = build_tts(tts_prov, tts_key or "", tts_voice)

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

            clip_specs = [
                ClipSpec(
                    path=c["path"],
                    trim_in=float(c["trim_in"]),
                    trim_out=float(c["trim_out"]),
                    script_text=c.get("script_text", ""),
                    use_llm_generation=bool(c.get("use_llm_generation", False)),
                )
                for c in config.get("clips", [])
            ]
            clipstory_config = ClipStoryConfig(
                topic=config.get("topic", ""),
                clips=clip_specs,
                output_resolution=config.get("output_resolution", "16:9"),
                tts_provider=tts_prov,
                tts_voice=tts_voice,
            )

            self._runner = ClipStoryRunner(config=clipstory_config, tts=tts, output_base=output_base)

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

- [ ] **Step 6: Verify existing modes still work — no unit test exists for bridge run-methods**

There is no dedicated pytest coverage for `start_shorts_run`/`start_slideshow_run`
themselves (confirmed: only `tests/unit/test_bridge_duration.py` exists, covering the pure
`duration_to_minutes` helper). Run the existing suite to confirm nothing broke at import
time:

Run: `.venv/bin/python -m pytest tests/unit/test_bridge_duration.py -v`
Expected: PASS (unchanged).

Run: `.venv/bin/python -c "from docu_studio.gui.bridge import Bridge; b = Bridge(); print(b.browse_videos, b.get_clip_metadata, b.generate_clipstory_narration, b.start_clipstory_run)"`
Expected: prints four bound method objects with no import errors — confirms the new
methods and their imports are syntactically valid and importable.

- [ ] **Step 7: Commit**

```bash
git add docu_studio/gui/bridge.py
git commit -m "feat(clipstory): wire Clip Story into Bridge (browse_videos, narration review, run)"
```

---

### Task 9: GUI — mode card, clip list, review step, cache-bust bump

**Files:**
- Modify: `docu_studio/gui/web/index.html`
- Modify: `docu_studio/gui/web/app.js`
- Modify: `docu_studio/gui/webview_app.py:33`

**Interfaces:**
- Consumes: `Bridge.browse_videos`, `Bridge.get_clip_metadata`,
  `Bridge.generate_clipstory_narration`, `Bridge.start_clipstory_run` (Task 8).
- Produces: no new Python interfaces — this is the frontend surface. No automated tests
  exist for the frontend anywhere in this repo (confirmed: no `.test.js` files, no JS test
  runner configured) — verified manually in Task 10.

- [ ] **Step 1: Add the Clip Story mode card in `index.html`**

Insert immediately after the existing Slideshow mode card (currently ending at line 204,
right before the closing `</div>` of the mode-cards grid at line 205):
```html
        <!-- Clip Story -->
        <div onclick="startConfig('clipstory')" class="anim-card col-span-2 bg-card border border-border rounded-xl p-8 hover:border-amber-400 transition-colors cursor-pointer">
          <div class="text-xs font-semibold tracking-widest text-amber-400">CLIP STORY MODE</div>
          <div class="text-xl font-semibold text-white mt-2">Compile your own footage into a narrated video</div>
          <p class="text-sm text-dim mt-3 leading-relaxed">Upload your own video clips in order, trim each one, and write (or flag for AI generation) narration for each — the app fits the narration to each clip's actual length and stitches them together.</p>
          <button class="mt-6 bg-amber-500 text-white font-semibold text-sm px-5 py-2.5 rounded-lg hover:bg-amber-600 transition-colors pointer-events-none">Start Clip Story →</button>
        </div>
```

- [ ] **Step 2: Add the Clip Story config-screen rows in `index.html`**

Insert immediately after the Slideshow music-toggle row's closing `</div>` (currently
ending at line 437, right before the "Start button" comment at line 439):
```html
        <!-- Topic (clipstory) -->
        <div id="clipstory-topic-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Topic</label>
          <input id="clipstory-topic-input" type="text"
            placeholder="e.g. Our trip to the mountains"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none placeholder-faint">
        </div>

        <!-- Output canvas (clipstory) -->
        <div id="clipstory-canvas-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Output canvas</label>
          <select id="clipstory-canvas-select"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="16:9">16:9 widescreen (1920 × 1080)</option>
            <option value="9:16">9:16 vertical (1080 × 1920)</option>
          </select>
        </div>

        <!-- Clips (clipstory) -->
        <div id="clipstory-clips-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Video clips</label>
          <button onclick="browseClipStoryClips()" type="button"
            class="mt-2 px-4 py-2 rounded-lg text-sm font-semibold bg-card border border-border text-dim hover:text-white hover:border-bstrong transition-colors">
            Choose videos…
          </button>
          <div id="clipstory-clip-list" class="mt-3 space-y-3"></div>
        </div>

        <!-- Generate narration + review (clipstory) -->
        <div id="clipstory-review-row" class="mt-6" style="display:none">
          <div class="flex items-center justify-between">
            <label class="text-sm font-medium text-dim block">Narration review</label>
            <button id="clipstory-generate-btn" onclick="generateClipStoryNarration()" type="button" disabled
              class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-faint cursor-not-allowed transition-colors">
              Generate Narration
            </button>
          </div>
          <div id="clipstory-review-list" class="mt-3 space-y-3"></div>
        </div>
```

- [ ] **Step 3: Update `startConfig(mode)` in `app.js` for the `clipstory` mode**

Modify the function (currently lines 205-242): add an `else if (mode === 'clipstory')`
branch to the badge if/else chain, and add clipstory row toggles to the flat
`_q('...-row').style.display = ...` list:
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
  } else if (mode === 'slideshow') {
    badge.textContent = 'Slideshow Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-emerald-900/40 text-emerald-300';
    _q('topic-row').style.display = 'none';
  } else if (mode === 'clipstory') {
    badge.textContent = 'Clip Story Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-amber-900/40 text-amber-300';
    _q('topic-row').style.display = 'none';
  } else {
    badge.textContent = 'Full Auto Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-purple-900/40 text-purple-300';
    _q('topic-row').style.display = 'none';
  }
  _q('doc-duration-row').style.display = (mode === 'short' || mode === 'slideshow' || mode === 'clipstory') ? 'none' : '';
  _q('short-duration-row').style.display = mode === 'short' ? '' : 'none';
  _q('aspect-row').style.display = mode === 'short' ? '' : 'none';
  _q('captions-row').style.display = mode === 'short' ? '' : 'none';
  _q('music-row').style.display = mode === 'short' ? '' : 'none';
  _q('advanced-row').style.display = mode === 'short' ? '' : 'none';
  _q('slideshow-topic-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-images-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-script-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-aspect-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-transition-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-vignette-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-grain-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-captions-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-music-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('clipstory-topic-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-canvas-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-clips-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-review-row').style.display = mode === 'clipstory' ? '' : 'none';
  onSlideshowMusicToggleChange();
  showScreen('config');
}
```

- [ ] **Step 4: Add Clip Story clip-list state and rendering functions in `app.js`**

Insert near the existing `let _slideshowImages = [];` (currently line 244), mirroring its
pattern with per-item state instead of bare paths:
```javascript
let _clipStoryClips = [];   // [{path, duration, posterPath, trimIn, trimOut, scriptText, useLlm}]
let _clipStoryReview = {};  // {index: {text, pace_estimate_seconds}}

async function browseClipStoryClips() {
  const paths = await window.pywebview.api.browse_videos();
  if (!paths || !paths.length) return;
  const meta = await window.pywebview.api.get_clip_metadata(paths);
  if (!meta.ok) { alert('Failed to read clip metadata: ' + meta.error); return; }
  meta.clips.forEach(c => {
    _clipStoryClips.push({
      path: c.path, duration: c.duration, posterPath: c.poster_path,
      trimIn: 0, trimOut: c.duration, scriptText: '', useLlm: false,
    });
  });
  _renderClipStoryClips();
}

function _renderClipStoryClips() {
  const list = _q('clipstory-clip-list');
  list.innerHTML = '';
  _clipStoryClips.forEach((clip, i) => {
    const row = document.createElement('div');
    row.className = 'bg-input border border-border rounded-lg px-3 py-3 text-sm text-white';

    const topRow = document.createElement('div');
    topRow.className = 'flex items-center gap-2';

    const thumb = document.createElement('img');
    thumb.src = _toFileUrl(clip.posterPath);
    thumb.className = 'w-14 h-10 object-cover rounded shrink-0';
    thumb.alt = '';
    topRow.appendChild(thumb);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'flex-1 truncate';
    nameSpan.textContent = `${i + 1}. ${clip.path.split(/[\\/]/).pop()} (${clip.duration.toFixed(1)}s)`;
    topRow.appendChild(nameSpan);

    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'text-faint hover:text-white px-1';
    upBtn.textContent = '↑';
    upBtn.onclick = () => _moveClipStoryClip(i, -1);
    topRow.appendChild(upBtn);

    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'text-faint hover:text-white px-1';
    downBtn.textContent = '↓';
    downBtn.onclick = () => _moveClipStoryClip(i, 1);
    topRow.appendChild(downBtn);

    const rmBtn = document.createElement('button');
    rmBtn.type = 'button';
    rmBtn.className = 'text-faint hover:text-red-400 px-1';
    rmBtn.textContent = '✕';
    rmBtn.onclick = () => _removeClipStoryClip(i);
    topRow.appendChild(rmBtn);

    row.appendChild(topRow);

    const trimRow = document.createElement('div');
    trimRow.className = 'mt-2 flex items-center gap-2 text-xs text-dim';
    trimRow.innerHTML = `
      <label>Trim in (s)</label>
      <input type="number" min="0" step="0.1" value="${clip.trimIn}" data-idx="${i}" data-field="trimIn"
        class="w-20 bg-panel border border-border rounded px-2 py-1 text-white">
      <label>Trim out (s)</label>
      <input type="number" min="0" step="0.1" value="${clip.trimOut}" data-idx="${i}" data-field="trimOut"
        class="w-20 bg-panel border border-border rounded px-2 py-1 text-white">
    `;
    trimRow.querySelectorAll('input').forEach(input => {
      input.onchange = (e) => _updateClipStoryTrim(i, e.target.dataset.field, parseFloat(e.target.value));
    });
    row.appendChild(trimRow);

    const scriptRow = document.createElement('div');
    scriptRow.className = 'mt-2';
    const llmLabel = document.createElement('label');
    llmLabel.className = 'flex items-center gap-2 text-xs text-dim';
    llmLabel.innerHTML = `<input type="checkbox" ${clip.useLlm ? 'checked' : ''} class="accent-accent"> Generate with AI`;
    llmLabel.querySelector('input').onchange = (e) => _updateClipStoryLlmFlag(i, e.target.checked);
    scriptRow.appendChild(llmLabel);
    if (!clip.useLlm) {
      const textarea = document.createElement('textarea');
      textarea.rows = 2;
      textarea.placeholder = 'Write narration for this clip…';
      textarea.value = clip.scriptText;
      textarea.className = 'mt-1 w-full bg-panel border border-border rounded px-2 py-1 text-white text-xs';
      textarea.onchange = (e) => _updateClipStoryScript(i, e.target.value);
      scriptRow.appendChild(textarea);
    }
    row.appendChild(scriptRow);

    list.appendChild(row);
  });
  _updateClipStoryGenerateButtonState();
}

function _moveClipStoryClip(i, delta) {
  const j = i + delta;
  if (j < 0 || j >= _clipStoryClips.length) return;
  [_clipStoryClips[i], _clipStoryClips[j]] = [_clipStoryClips[j], _clipStoryClips[i]];
  _renderClipStoryClips();
}

function _removeClipStoryClip(i) {
  _clipStoryClips.splice(i, 1);
  _renderClipStoryClips();
}

function _updateClipStoryTrim(i, field, value) {
  if (Number.isNaN(value)) return;
  _clipStoryClips[i][field] = value;
}

function _updateClipStoryScript(i, text) {
  _clipStoryClips[i].scriptText = text;
}

function _updateClipStoryLlmFlag(i, checked) {
  _clipStoryClips[i].useLlm = checked;
  if (checked) _clipStoryClips[i].scriptText = '';
  _renderClipStoryClips();
}

function _updateClipStoryGenerateButtonState() {
  const btn = _q('clipstory-generate-btn');
  if (!btn) return;
  const enabled = _clipStoryClips.length > 0 && _clipStoryClips.every(
    c => c.trimOut > c.trimIn && (c.useLlm || c.scriptText.trim().length > 0)
  );
  btn.disabled = !enabled;
  btn.className = enabled
    ? 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-dim hover:text-white hover:border-bstrong transition-colors cursor-pointer'
    : 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-faint cursor-not-allowed transition-colors';
}
```

- [ ] **Step 5: Add the review-step and render-gating functions in `app.js`**

```javascript
async function generateClipStoryNarration() {
  const topic = (_q('clipstory-topic-input')?.value || '').trim();
  const clips = _clipStoryClips.map(c => ({
    path: c.path, trim_in: c.trimIn, trim_out: c.trimOut,
    script_text: c.scriptText, use_llm_generation: c.useLlm,
  }));
  const res = await window.pywebview.api.generate_clipstory_narration(topic, clips);
  if (!res.ok) { alert('Narration generation failed: ' + res.error); return; }
  _clipStoryReview = res.review;
  _renderClipStoryReview();
}

function _renderClipStoryReview() {
  const list = _q('clipstory-review-list');
  list.innerHTML = '';
  Object.keys(_clipStoryReview).sort((a, b) => a - b).forEach(idx => {
    const entry = _clipStoryReview[idx];
    const clip = _clipStoryClips[idx];
    const targetDuration = (clip.trimOut - clip.trimIn).toFixed(1);
    const row = document.createElement('div');
    row.className = 'bg-input border border-border rounded-lg px-3 py-3 text-sm text-white';
    row.innerHTML = `
      <div class="text-xs text-faint">Clip ${Number(idx) + 1} — target ${targetDuration}s, estimated pace ${entry.pace_estimate_seconds.toFixed(1)}s</div>
      <textarea rows="3" data-idx="${idx}" class="mt-1 w-full bg-panel border border-border rounded px-2 py-1 text-white text-xs">${entry.text}</textarea>
    `;
    row.querySelector('textarea').onchange = (e) => {
      _clipStoryReview[idx].text = e.target.value;
      _clipStoryClips[idx].scriptText = e.target.value;
    };
    list.appendChild(row);
  });
  const startBtn = _q('start-run-btn');
  if (_runMode === 'clipstory') startBtn.disabled = Object.keys(_clipStoryReview).length !== _clipStoryClips.length;
}
```

- [ ] **Step 6: Wire `clipstory` into `startRun()` in `app.js`**

Modify `startRun()` (currently lines 405-477): add a `clipstory` branch before the
`slideshow` check:
```javascript
async function startRun() {
  const topic = (_q('topic-input')?.value || '').trim();
  if (_runMode === 'clipstory') {
    const clipsTopic = (_q('clipstory-topic-input')?.value || '').trim();
    if (Object.keys(_clipStoryReview).length !== _clipStoryClips.length) {
      alert('Please generate/review narration for every clip first.');
      return;
    }
    showScreen('progress');
    _resetProgress();
    startPolling();
    const res = await window.pywebview.api.start_clipstory_run({
      topic: clipsTopic,
      output_resolution: _q('clipstory-canvas-select').value,
      clips: _clipStoryClips.map((c, i) => ({
        path: c.path, trim_in: c.trimIn, trim_out: c.trimOut,
        script_text: _clipStoryReview[i].text, use_llm_generation: false,
      })),
    });
    if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
    return;
  }
  if (_runMode === 'slideshow') {
```
(The rest of the function is unchanged — this new block is inserted as the first branch,
before the existing `if (_runMode === 'slideshow') {` line. Note `use_llm_generation:
false` is intentional in the render-step payload — by render time every clip already has
finalized text from the review step, whether it originated from the LLM or the user, so
`ClipSpec`'s "exactly one of script_text/use_llm_generation" validation is satisfied with
the finalized text in both cases.)

- [ ] **Step 7: Add the Clip Story stage track and wire `_resetProgress`/`_setStage`/`_handleEvent`**

In `index.html`, insert immediately after the Slideshow stage-track div (currently ending
at line 486):
```html
      <div class="flex flex-wrap gap-2" id="clipstory-stage-track" style="display:none">
        <div id="clipstory-stage-0" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Assembly</div>
      </div>
```

In `app.js`, modify `_resetProgress()` (currently lines 492-501):
```javascript
const STAGES = ['Script','Scenes','Audio','Keywords','Footage','Sync','Timeline','Done'];
const SHORT_STAGES = ['Script','TTS','Alignment','Footage','Assembly','Captions & Music','Mux'];
const SLIDESHOW_STAGES = ['TTS','Assembly','Mux'];
const CLIPSTORY_STAGES = ['Assembly'];

function _resetProgress() {
  _q('progress-title').textContent = 'Generating…';
  _q('log-area').innerHTML = '';
  _q('open-folder-btn').style.display = 'none';
  _q('stage-track').style.display = (_runMode === 'short' || _runMode === 'slideshow' || _runMode === 'clipstory') ? 'none' : '';
  _q('shorts-stage-track').style.display = _runMode === 'short' ? '' : 'none';
  _q('slideshow-stage-track').style.display = _runMode === 'slideshow' ? '' : 'none';
  _q('clipstory-stage-track').style.display = _runMode === 'clipstory' ? '' : 'none';
  const stages = _runMode === 'short' ? SHORT_STAGES : _runMode === 'slideshow' ? SLIDESHOW_STAGES : _runMode === 'clipstory' ? CLIPSTORY_STAGES : STAGES;
  stages.forEach((_, i) => _setStage(i, 'pending'));
}
```

Modify `_setStage(i, state)` (currently lines 503-521), the `prefix` line only:
```javascript
function _setStage(i, state) {
  const prefix = _runMode === 'short' ? 'short-stage-' : _runMode === 'slideshow' ? 'slideshow-stage-' : _runMode === 'clipstory' ? 'clipstory-stage-' : 'stage-';
  const el = _q(prefix + i);
```

Modify `_handleEvent`'s completion-stage-index line (currently line 558):
```javascript
    _setStage(_runMode === 'short' ? 6 : _runMode === 'clipstory' ? 0 : _runMode === 'slideshow' ? 2 : 7, 'complete');
```
(This corrects the completion index for `clipstory`'s single-stage track; note Slideshow's
own branch is pre-existing and untouched here — only the new `clipstory` ternary arm is
added.)

- [ ] **Step 8: Bump the cache-busting version in `webview_app.py`**

In `docu_studio/gui/webview_app.py:33`, change:
```python
    the_url = str(WEB_DIR / "index.html") + "?v=12"
```
to:
```python
    the_url = str(WEB_DIR / "index.html") + "?v=13"
```

- [ ] **Step 9: Restart the app and smoke-test all four modes still load**

Run:
```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio
```
In the GUI: confirm the main screen shows all four mode cards (Guided, Full Auto,
Short/Reel, Slideshow, Clip Story), and clicking into Documentary/Short/Slideshow's config
screens still shows exactly the fields each had before this task (byte-for-byte behavior
check per the design spec's verification requirement) — do not start a real run yet, that
is Task 10.

- [ ] **Step 10: Commit**

```bash
git add docu_studio/gui/web/index.html docu_studio/gui/web/app.js docu_studio/gui/webview_app.py
git commit -m "feat(clipstory): add Clip Story GUI (mode card, clip list, narration review)"
```

---

### Task 10: Real end-to-end verification run

**Files:** none (verification only — the delivery checkpoint from the design spec).

**Interfaces:** N/A.

- [ ] **Step 1: Prepare 2-3 real test video clips of varying duration**

Use or record short real `.mp4` files (a phone clip, a screen recording, anything real —
not synthetic test fixtures) covering: one clip where natural-pace narration is close to
the clip's length, one clip trimmed short enough that Layer 2's atempo has to noticeably
speed up narration, and if feasible one clip trimmed so short that Layer 3's halt should
trigger on purpose (e.g. a 3-second trim with a long user-written script).

- [ ] **Step 2: Run a real Clip Story generation end-to-end**

```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio
```
In the GUI: click Clip Story, enter a topic, upload the test clips in order, set trim
in/out for each, write narration for at least one clip and flag at least one for LLM
generation, click Generate Narration, review the shown text/pace estimates, click the
render/start button.

- [ ] **Step 3: Inspect the halt case first (if triggered)**

If the deliberately-too-short clip triggered the Layer 3 halt: confirm the error panel
shows the real numbers (target/actual/ideal factor/applied factor/residual %) for that
clip, not a generic failure message. Fix that clip's trim/script and re-render.

- [ ] **Step 4: Inspect the successful output by eye, not just logs**

Open the final rendered video. Confirm: cut points land where trims were set (compare
against the source clips' timestamps), narration audibly fits each segment without
absurd speed distortion, any reconciliation padding/fade is inaudible or unobtrusive (no
abrupt pop where a clip was truncated), and the output canvas matches the selected
16:9/9:16 choice with no stretched/squashed video.

- [ ] **Step 5: Cross-check the log numbers for whichever clip invoked Layer 2 or 3**

```bash
grep -A2 "residual=" ~/DocuStudio/*/clipstory_log.txt 2>/dev/null | tail -20
```
(Or check the equivalent project-folder log path if `output_folder` was customized in
Settings.) Confirm the logged `applied_factor`/`residual` numbers for that clip are
consistent with what was visually/audibly observed in Step 4 — per the design spec, this
confirms success by checking real numbers, not by assuming the run succeeded because it
completed.

- [ ] **Step 6: Final full test suite run**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -10`
Expected: same failure/error count as the Task 0 baseline, all new `clipstory`/`tts_calibration` tests passing.

- [ ] **Step 7: Write the handoff notes**

No code change — report back (in the session, not a new file) what's verified-by-eyes
(Steps 3-5) vs. verified-by-logs-only, the final test count, any bugs found and fixed
during this real run, and what remains open for Phase 2 (captions, music, crossfade
transitions per the design spec's deferred scope).

---

## Plan self-review notes

- **Spec coverage:** Every section of `2026-07-13-clipstory-phase1-design.md` maps to a
  task — package structure (Tasks 2-7), decisions 1-8 (Tasks 2/4/5/6/8/9), data flow review
  step (Task 4 + Task 8 Step 4 + Task 9 Steps 4-5), data flow render step (Task 6 + Task 7
  + Task 8 Step 5 + Task 9 Step 6), GUI scope (Task 9), error handling (Tasks 6/7, reusing
  existing `ErrorEvent`), testing (every code task has its own test step), the
  `tts_calibration.py` move + its real-E2E requirement (Task 1), and the delivery
  checkpoint (Task 10).
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code or an exact
  shell command with expected output.
- **Type consistency check:** `ClipSpec`/`ClipStoryConfig` (Task 2) are imported with the
  same field names in Tasks 4, 6, 8; `FitResult`/`ReconciliationPlan` (Task 3) are
  consumed with the same field names in Tasks 5/6; `ClipStoryFFmpeg`'s four new method
  signatures (Task 5) match exactly how Task 6 calls them; `ClipStoryRunner`'s
  `event_queue`/`cancel_event`/`_project_folder`/`_final_video_path` attribute names
  (Task 7) match what Task 8's `_translate_events`/`_to_js_event` (unmodified, inherited
  from existing Bridge code) expect from any runner.
