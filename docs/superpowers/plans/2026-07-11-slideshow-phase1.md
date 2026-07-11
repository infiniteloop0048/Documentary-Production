# Slideshow Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a working "Slideshow" pipeline — manual image upload + user-supplied narration script + Ken Burns motion + hard-cut assembly — as a third mode alongside Documentary and Shorts, with zero changes to `shorts/`, `pipeline/`, `adapters/`, `history/`, or `licensing.py`.

**Architecture:** A fully self-contained `docu_studio/slideshow/` package (no `docu_studio/common/` extraction — Phase 1 doesn't need any of Shorts' shared infrastructure; see the design spec for why). `SlideshowRunner` mirrors `ShortsRunner`'s public shape so the existing GUI event-translation code works unmodified in spirit — a new `slideshow` branch is added alongside it, not inserted into it. `SlideshowFFmpeg` subclasses the shared `FFmpegWrapper` (same pattern as `ShortsFFmpeg`) and reuses `FFmpegWrapper.mux_audio_video`/`get_duration` directly rather than duplicating them.

**Tech Stack:** Python 3.11+, pywebview/Qt5, ffmpeg (via `imageio_ffmpeg`), existing TTS adapter factory (`gtts`/`elevenlabs`/`deepgram`), pytest with `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-07-11-slideshow-phase1-design.md`

## Global Constraints

- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files), `history/`, `licensing.py`, or existing test files, unless fixing an actual bug in them.
- Correct venv is `.venv/`, never `venv/`. Use `.venv/bin/python` for everything.
- Kill and restart the app before testing any change: `pkill -f docu_studio 2>/dev/null && DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Fresh baseline confirmed by this plan's own author immediately before writing it: **24 failed, 442 passed, 1 collection error** (`tests/integration/test_edge_tts_adapter.py` imports a nonexistent `docu_studio.adapters.tts.edge_tts_adapter` module — pre-existing, unrelated to Slideshow, do not fix). This corrects the design spec's carried-over "17 vs 24" uncertainty — **24 failed / 1 collection error is the confirmed number**. Every task's test run must not change this baseline except by adding new passing tests.
- Cache-busting `?v=N` in `webview_app.py` is currently `?v=10` (confirmed by reading the file) — bump to `?v=11` after the GUI task.
- Add a per-call log line to any new function whose behavior could silently regress on process-not-restarted (mirrors `detect_motion_window`'s version-marker line) — not required for every function, only ones a future debugging session would need to distinguish "old code still loaded" from "legitimately different input."
- Commit after each task. Do not push without explicit go-ahead.

---

### Task 1: `slideshow_config.py` — run configuration and aspect-ratio dimensions

**Files:**
- Create: `docu_studio/slideshow/__init__.py` (empty)
- Create: `docu_studio/slideshow/slideshow_config.py`
- Test: `tests/unit/test_slideshow_config.py`

**Interfaces:**
- Produces: `SLIDESHOW_ASPECT_DIMENSIONS: dict[str, tuple[int, int]]`, `SLIDESHOW_DEFAULT_ASPECT: str`, `SlideshowConfig` dataclass with fields `script_text: str`, `image_paths: list[str]`, `aspect_ratio: str = SLIDESHOW_DEFAULT_ASPECT`, property `output_dimensions -> tuple[int, int]`. Raises `ValueError` in `__post_init__` for empty `script_text`, empty `image_paths`, or unknown `aspect_ratio`.

- [ ] **Step 1: Create the package directory and empty `__init__.py`**

```bash
mkdir -p "docu_studio/slideshow"
touch "docu_studio/slideshow/__init__.py"
```

- [ ] **Step 2: Write the failing test**

```python
"""Unit tests for SlideshowConfig — pure dataclass validation, no I/O."""
from __future__ import annotations

import pytest

from docu_studio.slideshow.slideshow_config import (
    SLIDESHOW_ASPECT_DIMENSIONS,
    SLIDESHOW_DEFAULT_ASPECT,
    SlideshowConfig,
)


class TestSlideshowConfig:
    def test_valid_config_defaults_to_9_16(self) -> None:
        cfg = SlideshowConfig(script_text="Hello world.", image_paths=["/a.jpg"])
        assert cfg.aspect_ratio == SLIDESHOW_DEFAULT_ASPECT
        assert cfg.output_dimensions == (1080, 1920)

    def test_16_9_dimensions(self) -> None:
        cfg = SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], aspect_ratio="16:9")
        assert cfg.output_dimensions == (1920, 1080)

    def test_1_1_dimensions(self) -> None:
        cfg = SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], aspect_ratio="1:1")
        assert cfg.output_dimensions == (1080, 1080)

    def test_empty_script_text_raises(self) -> None:
        with pytest.raises(ValueError, match="script_text"):
            SlideshowConfig(script_text="   ", image_paths=["/a.jpg"])

    def test_empty_image_paths_raises(self) -> None:
        with pytest.raises(ValueError, match="image_paths"):
            SlideshowConfig(script_text="Hi.", image_paths=[])

    def test_unknown_aspect_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="aspect_ratio"):
            SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], aspect_ratio="4:3")

    def test_all_known_aspect_ratios_present(self) -> None:
        assert set(SLIDESHOW_ASPECT_DIMENSIONS) == {"9:16", "16:9", "1:1"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_config'`

- [ ] **Step 4: Write minimal implementation**

```python
"""Configuration for a single Slideshow generation run."""
from __future__ import annotations

from dataclasses import dataclass

SLIDESHOW_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
SLIDESHOW_DEFAULT_ASPECT = "9:16"


@dataclass
class SlideshowConfig:
    script_text: str
    image_paths: list[str]
    aspect_ratio: str = SLIDESHOW_DEFAULT_ASPECT

    def __post_init__(self) -> None:
        if not self.script_text.strip():
            raise ValueError("script_text must not be empty")
        if not self.image_paths:
            raise ValueError("image_paths must not be empty")
        if self.aspect_ratio not in SLIDESHOW_ASPECT_DIMENSIONS:
            raise ValueError(
                f"aspect_ratio must be one of {sorted(SLIDESHOW_ASPECT_DIMENSIONS)}, "
                f"got {self.aspect_ratio!r}"
            )

    @property
    def output_dimensions(self) -> tuple[int, int]:
        return SLIDESHOW_ASPECT_DIMENSIONS[self.aspect_ratio]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_config.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add docu_studio/slideshow/__init__.py docu_studio/slideshow/slideshow_config.py tests/unit/test_slideshow_config.py
git commit -m "feat(slideshow): add SlideshowConfig with aspect-ratio dimension table"
```

---

### Task 2: `slideshow_images.py` — manual image list validation

**Files:**
- Create: `docu_studio/slideshow/slideshow_images.py`
- Test: `tests/unit/test_slideshow_images.py`

**Interfaces:**
- Consumes: nothing (stdlib `pathlib.Path` only).
- Produces: `InvalidImageListError(ValueError)`, `validate_manual_images(paths: list[str]) -> list[str]` — returns the same paths (order preserved) if every entry exists and has a recognized image extension; raises `InvalidImageListError` otherwise.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for validate_manual_images — filesystem-backed, uses tmp_path."""
from __future__ import annotations

from pathlib import Path

import pytest

from docu_studio.slideshow.slideshow_images import (
    InvalidImageListError,
    validate_manual_images,
)


class TestValidateManualImages:
    def test_empty_list_raises(self) -> None:
        with pytest.raises(InvalidImageListError, match="At least one image"):
            validate_manual_images([])

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidImageListError, match="not found"):
            validate_manual_images([str(tmp_path / "missing.jpg")])

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "notes.txt"
        bad.write_text("hi")
        with pytest.raises(InvalidImageListError, match="Unsupported image format"):
            validate_manual_images([str(bad)])

    def test_valid_list_preserves_order(self, tmp_path: Path) -> None:
        first = tmp_path / "b.png"
        second = tmp_path / "a.jpg"
        first.write_bytes(b"\x89PNG")
        second.write_bytes(b"\xff\xd8\xff")
        result = validate_manual_images([str(first), str(second)])
        assert result == [str(first), str(second)]

    def test_case_insensitive_extension(self, tmp_path: Path) -> None:
        upper = tmp_path / "photo.JPG"
        upper.write_bytes(b"\xff\xd8\xff")
        assert validate_manual_images([str(upper)]) == [str(upper)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_images.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_images'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Manual image source for Slideshow — Phase 1 only supports a user-supplied
ordered list. Topic-based fetch is Phase 2."""
from __future__ import annotations

from pathlib import Path

_VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class InvalidImageListError(ValueError):
    """Raised when a manual image list fails validation."""


def validate_manual_images(paths: list[str]) -> list[str]:
    """Validate a user-supplied ordered image list.

    Returns the same paths (order preserved) if every entry exists and has
    a recognized image extension. Raises InvalidImageListError with a clear
    message otherwise — this is the fail-fast boundary check, called before
    any TTS synthesis or ffmpeg work starts.
    """
    if not paths:
        raise InvalidImageListError("At least one image is required.")
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise InvalidImageListError(f"Image not found: {p}")
        if path.suffix.lower() not in _VALID_EXTENSIONS:
            raise InvalidImageListError(
                f"Unsupported image format: {p} "
                f"(expected one of {sorted(_VALID_EXTENSIONS)})"
            )
    return list(paths)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_images.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_images.py tests/unit/test_slideshow_images.py
git commit -m "feat(slideshow): add manual image list validation"
```

---

### Task 3: `slideshow_motion.py` — Ken Burns direction selection

**Files:**
- Create: `docu_studio/slideshow/slideshow_motion.py`
- Test: `tests/unit/test_slideshow_motion.py`

**Interfaces:**
- Produces: `direction_for_index(index: int) -> str` — returns `"in"` for even indices, `"out"` for odd indices (alternating so consecutive segments don't all zoom the same way). Phase 1 supports only these two directions; pan/rotation/mixed-random are Phase 3.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for Ken Burns direction selection."""
from __future__ import annotations

from docu_studio.slideshow.slideshow_motion import direction_for_index


class TestDirectionForIndex:
    def test_even_indices_zoom_in(self) -> None:
        assert direction_for_index(0) == "in"
        assert direction_for_index(2) == "in"

    def test_odd_indices_zoom_out(self) -> None:
        assert direction_for_index(1) == "out"
        assert direction_for_index(3) == "out"

    def test_alternates_across_a_run(self) -> None:
        assert [direction_for_index(i) for i in range(5)] == ["in", "out", "in", "out", "in"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_motion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_motion'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Ken Burns motion selection for Slideshow.

Phase 1 supports classic zoom in/out only. Pan, rotation, and mixed-random
variants are Phase 3.
"""
from __future__ import annotations

_DIRECTIONS = ("in", "out")


def direction_for_index(index: int) -> str:
    """Alternate zoom-in/zoom-out per image so consecutive segments don't
    all zoom the same way."""
    return _DIRECTIONS[index % 2]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_motion.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_motion.py tests/unit/test_slideshow_motion.py
git commit -m "feat(slideshow): add alternating Ken Burns direction selection"
```

---

### Task 4: `slideshow_ffmpeg.py` — image Ken Burns + hard-cut concat

**Files:**
- Create: `docu_studio/slideshow/slideshow_ffmpeg.py`
- Test: `tests/unit/test_slideshow_ffmpeg.py`

**Interfaces:**
- Consumes: `docu_studio.media.ffmpeg_wrapper.FFmpegWrapper` (base class — `_ffmpeg`, `_ffprobe`, `_check()`, and inherited `get_duration()`/`mux_audio_video()`, never edited).
- Produces: `SlideshowFFmpeg(FFmpegWrapper)` with `_finalize_filter(filter_chain: str) -> str` (static), `apply_ken_burns_image(input_path: str, output_path: str, duration: float, direction: str, out_width: int, out_height: int) -> None`, `concat_segments_video_only(input_paths: list[str], output_path: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for SlideshowFFmpeg — subprocess mocked, no real ffmpeg
required, matching test_shorts_ffmpeg.py's convention."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg


@pytest.fixture
def wrapper() -> SlideshowFFmpeg:
    with patch("docu_studio.media.ffmpeg_wrapper.imageio_ffmpeg") as mock_ffmpeg_mod:
        mock_ffmpeg_mod.get_ffmpeg_exe.return_value = "/fake/ffmpeg"
        with patch("docu_studio.media.ffmpeg_wrapper.platform_layer") as mock_pl:
            mock_pl.ffprobe_exe.return_value = "/fake/ffprobe"
            return SlideshowFFmpeg()


class TestFinalizeFilter:
    def test_appends_sar_pixfmt_suffix(self, wrapper: SlideshowFFmpeg) -> None:
        assert wrapper._finalize_filter("scale=100:100") == "scale=100:100,setsar=1,format=yuv420p"


class TestApplyKenBurnsImage:
    def test_loops_the_still_image_input(self, wrapper: SlideshowFFmpeg) -> None:
        # A still image is a single-frame source; without -loop 1 ffmpeg
        # would exhaust it after one frame and zoompan would have nothing
        # to animate across `duration` seconds.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)
        cmd = mock_run.call_args[0][0]
        assert "-loop" in cmd
        assert cmd[cmd.index("-loop") + 1] == "1"
        assert cmd[cmd.index("-i") - 1] == "1"  # -loop 1 immediately precedes -i

    def test_crops_to_target_aspect_before_upscale(self, wrapper: SlideshowFFmpeg) -> None:
        # Unlike Shorts (which pre-crops to 1080x1920 via a separate
        # vertical_convert pass before Ken Burns ever runs), a still image
        # arrives at its native size — the crop-to-target-aspect step has
        # to be folded into this same filter chain.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1920, 1080)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "scale=1920:1080:force_original_aspect_ratio=increase" in vf
        assert "crop=1920:1080" in vf

    def test_upscales_4x_before_zoompan(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "scale=4320:-2:flags=lanczos" in vf

    def test_zoom_in_expression_is_non_accumulating(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", duration=1.0, direction="in",
                                           out_width=1080, out_height=1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        # duration=1.0 @ fps=30 -> frames=30, denom=29
        assert "z='1+0.08*on/29'" in vf

    def test_zoom_out_expression(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", duration=1.0, direction="out",
                                           out_width=1080, out_height=1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "z='1.08-0.08*on/29'" in vf

    def test_finalize_suffix_present(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf.endswith("setsar=1,format=yuv420p")

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError, match="boom"):
                wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)


class TestConcatSegmentsVideoOnly:
    def test_builds_filter_complex_concat(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_video_only(["/a.mp4", "/b.mp4", "/c.mp4"], "/out.mp4")
        cmd = mock_run.call_args[0][0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert filter_complex == "[0:v][1:v][2:v]concat=n=3:v=1:a=0[vout]"
        assert cmd.count("-i") == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_ffmpeg'`

- [ ] **Step 3: Write minimal implementation**

```python
"""FFmpeg operations specific to Slideshow assembly.

Subclasses FFmpegWrapper to reuse its ffmpeg/ffprobe binary resolution, the
_check() error-raising helper, get_duration(), and mux_audio_video() — the
base class is never edited, only extended, same discipline as ShortsFFmpeg.

apply_ken_burns_image reuses the Ken Burns fix verbatim from
docu_studio/shorts/shorts_ffmpeg.py (4x lanczos upscale before zoompan,
non-accumulating zoom expression, setsar=1/format=yuv420p finalize) but
generalizes it two ways Shorts doesn't need: output width/height are
parameters (Shorts hardcodes 1080x1920), and the crop-to-target-aspect step
is folded into the same filter chain (Shorts does that separately in
vertical_convert before Ken Burns ever runs on video; a still image has no
separate pre-crop pass).
"""
from __future__ import annotations

import subprocess

from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

# Same rationale as shorts_ffmpeg.py's _SAR_PIXFMT_SUFFIX: chained scale
# operations can round the encoded SAR to a near-1:1-but-not-exact value,
# and ffmpeg's concat filter rejects segments whose SAR doesn't match
# exactly. Every per-segment filter chain must end with this suffix.
_SAR_PIXFMT_SUFFIX = "setsar=1,format=yuv420p"


class SlideshowFFmpeg(FFmpegWrapper):
    """FFmpeg operations used only by the Slideshow assembly path."""

    @staticmethod
    def _finalize_filter(filter_chain: str) -> str:
        return f"{filter_chain},{_SAR_PIXFMT_SUFFIX}"

    def apply_ken_burns_image(
        self, input_path: str, output_path: str, duration: float,
        direction: str, out_width: int, out_height: int,
    ) -> None:
        """Render *duration* seconds of Ken Burns motion over a still image
        at *out_width*x*out_height*.

        direction='in' zooms 1.0->1.08, direction='out' zooms 1.08->1.0.
        -loop 1 is required because a still image is a single-frame input —
        without it ffmpeg has nothing left to feed zoompan after frame one.
        """
        fps = 30
        frames = max(1, round(duration * fps))
        denom = max(frames - 1, 1)
        target_zoom = 1.08
        zoom_delta = target_zoom - 1.0
        if direction == "in":
            zoom_expr = f"1+{zoom_delta}*on/{denom}"
        else:
            zoom_expr = f"{target_zoom}-{zoom_delta}*on/{denom}"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
        upscale_dim = out_width * 4
        vf = self._finalize_filter(
            f"scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
            f"crop={out_width}:{out_height},"
            f"scale={upscale_dim}:-2:flags=lanczos,"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={out_width}x{out_height}:fps={fps}"
        )
        cmd = [
            self._ffmpeg, "-y",
            "-loop", "1",
            "-i", input_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_ken_burns_image({direction}) → {output_path!r}")

    def concat_segments_video_only(self, input_paths: list[str], output_path: str) -> None:
        """Concatenate already-Ken-Burns'd segment videos (video only, hard
        cut). Same filter_complex-concat technique as
        ShortsFFmpeg.concat_segments_video_only — copied rather than
        imported to keep this package's only dependency on shorts/ at zero,
        per the Phase 1 design decision to defer all shared-code extraction."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_ffmpeg.py tests/unit/test_slideshow_ffmpeg.py
git commit -m "feat(slideshow): add SlideshowFFmpeg with generalized image Ken Burns"
```

---

### Task 5: `slideshow_assembly.py` — duration split + orchestration

**Files:**
- Create: `docu_studio/slideshow/slideshow_assembly.py`
- Test: `tests/unit/test_slideshow_assembly.py`

**Interfaces:**
- Consumes: `SlideshowFFmpeg` (Task 4) — calls `.apply_ken_burns_image(...)`, `.concat_segments_video_only(...)`, and the inherited `.mux_audio_video(...)`. Consumes `direction_for_index` (Task 3). Consumes `docu_studio.pipeline.events.{LogEvent, LogLevel, ProgressEvent}` (existing, shared, not shorts-specific).
- Produces: `split_duration_evenly(total_duration: float, count: int) -> list[float]`, `assemble_slideshow(image_paths: list[str], audio_path: str, audio_duration: float, ffmpeg: SlideshowFFmpeg, scene_dir: Path, output_path: Path, out_width: int, out_height: int, event_queue: "queue.Queue[object]") -> None`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for slideshow_assembly — ffmpeg mocked, no real ffmpeg or I/O."""
from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from docu_studio.slideshow.slideshow_assembly import assemble_slideshow, split_duration_evenly


class TestSplitDurationEvenly:
    def test_even_split_sums_exactly(self) -> None:
        durations = split_duration_evenly(10.0, 4)
        assert len(durations) == 4
        assert sum(durations) == pytest.approx(10.0)

    def test_remainder_absorbed_by_last_segment(self) -> None:
        durations = split_duration_evenly(10.0, 3)
        assert durations[0] == durations[1]
        assert sum(durations) == pytest.approx(10.0)

    def test_single_image_gets_full_duration(self) -> None:
        assert split_duration_evenly(7.5, 1) == [7.5]

    def test_zero_count_raises(self) -> None:
        with pytest.raises(ValueError, match="count must be positive"):
            split_duration_evenly(10.0, 0)


class TestAssembleSlideshow:
    def test_builds_one_segment_per_image_in_order(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        images = ["/img0.jpg", "/img1.jpg", "/img2.jpg"]
        assemble_slideshow(
            image_paths=images,
            audio_path="/narration.mp3",
            audio_duration=9.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        assert ffmpeg.apply_ken_burns_image.call_count == 3
        first_call_args = ffmpeg.apply_ken_burns_image.call_args_list[0].args
        assert first_call_args[0] == "/img0.jpg"
        assert first_call_args[3] == "in"   # direction_for_index(0)
        assert first_call_args[4:] == (1080, 1920)

    def test_concats_then_muxes(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"],
            audio_path="/narration.mp3",
            audio_duration=3.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        ffmpeg.concat_segments_video_only.assert_called_once()
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )

    def test_segment_failure_raises_with_index_and_image(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        ffmpeg.apply_ken_burns_image.side_effect = RuntimeError("ffmpeg exploded")
        event_queue: "queue.Queue[object]" = queue.Queue()
        with pytest.raises(RuntimeError, match="Segment 0.*img0.jpg"):
            assemble_slideshow(
                image_paths=["/img0.jpg"],
                audio_path="/narration.mp3",
                audio_duration=3.0,
                ffmpeg=ffmpeg,
                scene_dir=tmp_path,
                output_path=tmp_path / "final.mp4",
                out_width=1080,
                out_height=1920,
                event_queue=event_queue,
            )

    def test_progress_events_emitted(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"],
            audio_path="/narration.mp3",
            audio_duration=3.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        stages = []
        while not event_queue.empty():
            ev = event_queue.get_nowait()
            if hasattr(ev, "stage"):
                stages.append(ev.stage)
        assert "Slideshow Assembly" in stages
        assert "Slideshow Mux" in stages
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_assembly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_assembly'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Audio-first assembly for Slideshow: TTS duration -> even image split ->
Ken Burns -> hard-cut concat -> mux narration audio over the result.

Deliberately does not use sentence_spans()/word-timing/sentence-scoped pool
assignment — those solve a problem (aligning per-sentence narration to
per-sentence *searched* image results) that doesn't exist yet with a flat,
manually-ordered image list and no topic search. See the Phase 1 design
spec for why this is out of scope here.
"""
from __future__ import annotations

import logging
from pathlib import Path

from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
from docu_studio.slideshow.slideshow_motion import direction_for_index

_log = logging.getLogger(__name__)


def split_duration_evenly(total_duration: float, count: int) -> list[float]:
    """Split *total_duration* into *count* segment durations that sum
    exactly to *total_duration*. All segments get the same duration except
    the last, which absorbs the rounding remainder."""
    if count <= 0:
        raise ValueError("count must be positive")
    base = round(total_duration / count, 3)
    durations = [base] * (count - 1)
    last = round(total_duration - sum(durations), 3)
    durations.append(last)
    return durations


def assemble_slideshow(
    image_paths: list[str],
    audio_path: str,
    audio_duration: float,
    ffmpeg: SlideshowFFmpeg,
    scene_dir: Path,
    output_path: Path,
    out_width: int,
    out_height: int,
    event_queue,
) -> None:
    """Build the final slideshow video: one Ken-Burns segment per image,
    durations evenly splitting *audio_duration*, hard-cut concat, narration
    audio muxed over the result."""
    durations = split_duration_evenly(audio_duration, len(image_paths))

    event_queue.put(ProgressEvent(
        stage="Slideshow Assembly", message=f"Building {len(image_paths)} segments…",
    ))
    segment_paths: list[str] = []
    for i, (image_path, duration) in enumerate(zip(image_paths, durations)):
        direction = direction_for_index(i)
        seg_path = str(scene_dir / f"seg_{i:03d}.mp4")
        try:
            ffmpeg.apply_ken_burns_image(
                image_path, seg_path, duration, direction, out_width, out_height,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Segment {i} (image {image_path!r}) failed to render: {exc}"
            ) from exc
        segment_paths.append(seg_path)
        _log.info(
            "Segment %d: image=%s duration=%.2f direction=%s",
            i, image_path, duration, direction,
        )

    concat_path = str(scene_dir / "slideshow_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)

    event_queue.put(ProgressEvent(stage="Slideshow Mux", message="Muxing final slideshow…"))
    ffmpeg.mux_audio_video(concat_path, audio_path, str(output_path))

    event_queue.put(LogEvent(
        message=f"Slideshow assembled: {len(image_paths)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_assembly.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_assembly.py tests/unit/test_slideshow_assembly.py
git commit -m "feat(slideshow): add audio-first duration-split assembly orchestration"
```

---

### Task 6: `slideshow_runner.py` — background-thread orchestrator

**Files:**
- Create: `docu_studio/slideshow/slideshow_runner.py`
- Test: `tests/unit/test_slideshow_runner.py`
- Modify: nothing outside `docu_studio/slideshow/`

**Interfaces:**
- Consumes: `SlideshowConfig` (Task 1), `validate_manual_images` (Task 2), `SlideshowFFmpeg` (Task 4), `assemble_slideshow` (Task 5), `docu_studio.adapters.tts.base.TTSProvider` (existing, shared — `.synthesize(text, output_path) -> float`), `docu_studio.output.project_folder.create_project_folder` (existing, shared), `docu_studio.history.run_history.{RunRecord, save_run}` (existing, shared — `RunRecord.mode` is a plain `str`, no `Literal` constraint, confirmed by reading `history/run_history.py:22` — `"slideshow"` is a valid value with zero changes to that file).
- Produces: `SlideshowRunStatus(str, Enum)` with `COMPLETED`/`CANCELLED`/`FAILED`; `SlideshowRunner(threading.Thread)` with public shape matching `ShortsRunner`: `__init__(script_text, image_paths, tts, output_base, aspect_ratio="9:16")`, `self.event_queue: queue.Queue`, `self.cancel_event: threading.Event`, `self._project_folder: Path | None`, `self._final_video_path: Path | None`, `.run()`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for SlideshowRunner — TTS/ffmpeg fully mocked, no real
synthesis, ffmpeg, or filesystem I/O beyond tmp_path."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.slideshow.slideshow_runner import SlideshowRunner, SlideshowRunStatus


def _drain(runner: SlideshowRunner) -> list[object]:
    events = []
    while True:
        ev = runner.event_queue.get_nowait()
        if ev is None:
            break
        events.append(ev)
    return events


class TestSlideshowRunner:
    def test_invalid_config_raises_before_thread_starts(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="image_paths"):
            SlideshowRunner(
                script_text="Hello.", image_paths=[], tts=MagicMock(), output_base=tmp_path,
            )

    def test_successful_run_sets_completed_status(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0

        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            runner.run()

        assert runner._status == SlideshowRunStatus.COMPLETED
        assert runner._final_video_path is not None
        mock_assemble.assert_called_once()
        events = _drain(runner)
        assert any(getattr(e, "stage", "") == "Done" for e in events)

    def test_cancel_before_start_short_circuits(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
        )
        runner.cancel_event.set()
        with patch("docu_studio.slideshow.slideshow_runner.save_run"):
            runner.run()
        assert runner._status == SlideshowRunStatus.CANCELLED
        tts.synthesize.assert_not_called()

    def test_missing_image_file_fails_the_run(self, tmp_path: Path) -> None:
        # SlideshowConfig only checks the list is non-empty; per-path
        # existence is validate_manual_images' job, called at execution
        # time (a file could vanish between GUI selection and Start click).
        tts = MagicMock()
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(tmp_path / "gone.jpg")],
            tts=tts, output_base=tmp_path,
        )
        with patch("docu_studio.slideshow.slideshow_runner.save_run"):
            runner.run()
        assert runner._status == SlideshowRunStatus.FAILED
        events = _drain(runner)
        assert any("not found" in getattr(e, "message", "") for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_runner'`

- [ ] **Step 3: Write minimal implementation**

```python
"""SlideshowRunner — background thread that orchestrates the Slideshow
pipeline.

Mirrors ShortsRunner's public shape (event_queue, cancel_event,
_final_video_path, _project_folder, run()) so Bridge._translate_events()
works unmodified for slideshow runs — a new branch is added alongside
start_shorts_run, not into it. Does not import anything from
docu_studio.shorts, per the Phase 1 design decision to defer all shared
infrastructure extraction until a later phase actually needs it.
"""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.slideshow.slideshow_assembly import assemble_slideshow
from docu_studio.slideshow.slideshow_config import SlideshowConfig
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
from docu_studio.slideshow.slideshow_images import validate_manual_images


class SlideshowRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SlideshowRunner(threading.Thread):
    def __init__(
        self,
        script_text: str,
        image_paths: list[str],
        tts: TTSProvider,
        output_base: Path,
        aspect_ratio: str = "9:16",
    ) -> None:
        super().__init__(daemon=True, name="SlideshowRunner")
        self.config = SlideshowConfig(
            script_text=script_text, image_paths=image_paths, aspect_ratio=aspect_ratio,
        )
        self.tts = tts
        self.output_base = output_base

        self.event_queue: "queue.Queue[object]" = queue.Queue()
        self.cancel_event = threading.Event()

        self._status = SlideshowRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = SlideshowRunStatus.FAILED
        finally:
            self._save_history()
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        images = validate_manual_images(self.config.image_paths)
        self._project_folder = create_project_folder(
            "slideshow", self._started_at, self.output_base
        )
        ffmpeg = SlideshowFFmpeg()

        self.event_queue.put(ProgressEvent(
            stage="Slideshow TTS", message="Synthesizing narration…",
        ))
        audio_path = str(self._project_folder / "audio" / "narration.mp3")
        audio_duration = self.tts.synthesize(self.config.script_text, audio_path)
        self.event_queue.put(LogEvent(
            message=f"Narration: {audio_duration:.2f}s", level=LogLevel.INFO,
        ))
        if self._cancelled():
            return

        out_width, out_height = self.config.output_dimensions
        output_path = self._project_folder / "slideshow_final.mp4"
        assemble_slideshow(
            image_paths=images,
            audio_path=audio_path,
            audio_duration=audio_duration,
            ffmpeg=ffmpeg,
            scene_dir=self._project_folder / "video",
            output_path=output_path,
            out_width=out_width,
            out_height=out_height,
            event_queue=self.event_queue,
        )
        if self._cancelled():
            return

        self._final_video_path = output_path
        self._status = SlideshowRunStatus.COMPLETED
        self.event_queue.put(ProgressEvent(
            stage="Done", message=f"Slideshow completed: {output_path}",
        ))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = SlideshowRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic="Slideshow",
                mode="slideshow",
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_runner.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the full suite and confirm the baseline hasn't regressed**

Run: `.venv/bin/python -m pytest -q --continue-on-collection-errors`
Expected: `24 failed, 478 passed, 1 error` (442 baseline + 36 new Slideshow tests: 7 config + 5 images + 3 motion + 9 ffmpeg + 8 assembly + 4 runner). The failed/error count must be unchanged from the pre-Task-1 baseline (24 failed / 1 error) — only the passed count grows.

- [ ] **Step 6: Commit**

```bash
git add docu_studio/slideshow/slideshow_runner.py tests/unit/test_slideshow_runner.py
git commit -m "feat(slideshow): add SlideshowRunner orchestrator"
```

---

### Task 7: GUI wiring — Slideshow mode card, config screen, bridge methods

**Files:**
- Modify: `docu_studio/gui/web/index.html` (add mode card, config rows, stage-track div)
- Modify: `docu_studio/gui/web/app.js` (add `startConfig`/`startRun` branches, image-list JS, generalize `_resetProgress`/`_setStage`)
- Modify: `docu_studio/gui/bridge.py` (add `start_slideshow_run`, `browse_images`, `_SLIDESHOW_STAGE_MAP`, extend `_FINAL_STAGE_INDEX_BY_MODE`, extend `_to_js_event`'s stage-map selection)
- Modify: `docu_studio/gui/webview_app.py` (bump cache-bust `?v=10` -> `?v=11`)

**Interfaces:**
- Consumes: `SlideshowRunner` (Task 6), `docu_studio.adapters.tts.factory.build_tts` (existing, shared, already used by `start_shorts_run` — read-only reuse of the exact same construction logic), `docu_studio.config.key_cache`, `docu_studio.config.settings.Settings` (existing, both already imported in `bridge.py`).
- Produces: `Bridge.start_slideshow_run(config: dict) -> dict`, `Bridge.browse_images() -> list[str]`, JS globals `_slideshowImages: string[]`, `browseSlideshowImages()`, `_renderSlideshowImages()`, `_moveSlideshowImage(i, delta)`, `_removeSlideshowImage(i)`.

- [ ] **Step 1: Add the Slideshow mode card to `index.html`**

In `docu_studio/gui/web/index.html`, immediately after the existing "Short / Reel" card (the `</div>` that closes the card starting at the line with `onclick="startConfig('short')"`, itself inside the `grid grid-cols-2 gap-6` container), add:

```html
        <!-- Slideshow -->
        <div onclick="startConfig('slideshow')" class="anim-card col-span-2 bg-card border border-border rounded-xl p-8 hover:border-emerald-400 transition-colors cursor-pointer">
          <div class="text-xs font-semibold tracking-widest text-emerald-400">SLIDESHOW MODE</div>
          <div class="text-xl font-semibold text-white mt-2">Turn images into a narrated video</div>
          <p class="text-sm text-dim mt-3 leading-relaxed">Upload a set of images and write (or paste) a narration script. The app adds Ken Burns motion to each image, times it to your voiceover, and exports a finished video.</p>
          <button class="mt-6 bg-emerald-500 text-white font-semibold text-sm px-5 py-2.5 rounded-lg hover:bg-emerald-600 transition-colors pointer-events-none">Start slideshow →</button>
        </div>
```

- [ ] **Step 2: Add the Slideshow config rows to `index.html`**

Immediately after the existing "Advanced toggles (short/reel)" `</details>` block (before the "Start button" comment), add:

```html
        <!-- Images (slideshow) -->
        <div id="slideshow-images-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Images</label>
          <button onclick="browseSlideshowImages()" type="button"
            class="mt-2 px-4 py-2 rounded-lg text-sm font-semibold bg-card border border-border text-dim hover:text-white hover:border-bstrong transition-colors">
            Choose images…
          </button>
          <div id="slideshow-image-list" class="mt-3 space-y-2"></div>
        </div>

        <!-- Script (slideshow) -->
        <div id="slideshow-script-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Narration script</label>
          <textarea id="slideshow-script-input" rows="6"
            placeholder="Paste or write the narration script for your slideshow…"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none placeholder-faint"></textarea>
        </div>

        <!-- Aspect ratio (slideshow) -->
        <div id="slideshow-aspect-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Aspect ratio</label>
          <select id="slideshow-aspect-select"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="9:16">9:16 vertical (1080 × 1920)</option>
            <option value="16:9">16:9 widescreen (1920 × 1080)</option>
            <option value="1:1">1:1 square (1080 × 1080)</option>
          </select>
        </div>
```

- [ ] **Step 3: Add the Slideshow stage-track div to `index.html`**

Immediately after the existing `<div ... id="shorts-stage-track" ...>` block's closing `</div>`, add:

```html
      <div class="flex flex-wrap gap-2" id="slideshow-stage-track" style="display:none">
        <div id="slideshow-stage-0" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>TTS</div>
        <div id="slideshow-stage-1" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Assembly</div>
        <div id="slideshow-stage-2" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Mux</div>
      </div>
```

- [ ] **Step 4: Extend `startConfig()` in `app.js`**

Replace:

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
  _q('captions-row').style.display = mode === 'short' ? '' : 'none';
  _q('music-row').style.display = mode === 'short' ? '' : 'none';
  _q('advanced-row').style.display = mode === 'short' ? '' : 'none';
  showScreen('config');
}
```

with:

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
  } else {
    badge.textContent = 'Full Auto Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-purple-900/40 text-purple-300';
    _q('topic-row').style.display = 'none';
  }
  _q('doc-duration-row').style.display = (mode === 'short' || mode === 'slideshow') ? 'none' : '';
  _q('short-duration-row').style.display = mode === 'short' ? '' : 'none';
  _q('aspect-row').style.display = mode === 'short' ? '' : 'none';
  _q('captions-row').style.display = mode === 'short' ? '' : 'none';
  _q('music-row').style.display = mode === 'short' ? '' : 'none';
  _q('advanced-row').style.display = mode === 'short' ? '' : 'none';
  _q('slideshow-images-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-script-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-aspect-row').style.display = mode === 'slideshow' ? '' : 'none';
  showScreen('config');
}
```

- [ ] **Step 5: Add the image-list management functions to `app.js`**

Immediately after `startConfig()`, add:

```javascript
let _slideshowImages = [];

async function browseSlideshowImages() {
  const paths = await window.pywebview.api.browse_images();
  if (paths && paths.length) {
    _slideshowImages = _slideshowImages.concat(paths);
    _renderSlideshowImages();
  }
}

function _renderSlideshowImages() {
  const list = _q('slideshow-image-list');
  list.innerHTML = '';
  _slideshowImages.forEach((path, i) => {
    const row = document.createElement('div');
    row.className = 'flex items-center gap-2 bg-input border border-border rounded-lg px-3 py-2 text-sm text-white';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'flex-1 truncate';
    nameSpan.textContent = `${i + 1}. ${path.split(/[\\/]/).pop()}`;
    row.appendChild(nameSpan);

    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'text-faint hover:text-white px-1';
    upBtn.textContent = '↑';
    upBtn.onclick = () => _moveSlideshowImage(i, -1);
    row.appendChild(upBtn);

    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'text-faint hover:text-white px-1';
    downBtn.textContent = '↓';
    downBtn.onclick = () => _moveSlideshowImage(i, 1);
    row.appendChild(downBtn);

    const rmBtn = document.createElement('button');
    rmBtn.type = 'button';
    rmBtn.className = 'text-faint hover:text-red-400 px-1';
    rmBtn.textContent = '✕';
    rmBtn.onclick = () => _removeSlideshowImage(i);
    row.appendChild(rmBtn);

    list.appendChild(row);
  });
}

function _moveSlideshowImage(i, delta) {
  const j = i + delta;
  if (j < 0 || j >= _slideshowImages.length) return;
  [_slideshowImages[i], _slideshowImages[j]] = [_slideshowImages[j], _slideshowImages[i]];
  _renderSlideshowImages();
}

function _removeSlideshowImage(i) {
  _slideshowImages.splice(i, 1);
  _renderSlideshowImages();
}
```

Note: Phase 1 uses up/down buttons for reordering rather than drag-and-drop — satisfies the "reorder" requirement without pulling in a drag-and-drop library for a single-image-list use case. Revisit only if user feedback specifically asks for drag reordering.

- [ ] **Step 6: Add the slideshow branch to `startRun()` in `app.js`**

Replace the start of `startRun()`:

```javascript
async function startRun() {
  const topic = (_q('topic-input')?.value || '').trim();
  if (_runMode === 'short') {
```

with:

```javascript
async function startRun() {
  const topic = (_q('topic-input')?.value || '').trim();
  if (_runMode === 'slideshow') {
    const scriptText = (_q('slideshow-script-input')?.value || '').trim();
    if (!scriptText) {
      _q('slideshow-script-input').focus();
      _q('slideshow-script-input').classList.add('border-red-500');
      return;
    }
    if (_slideshowImages.length === 0) {
      alert('Please choose at least one image.');
      return;
    }
    showScreen('progress');
    _resetProgress();
    startPolling();
    const res = await window.pywebview.api.start_slideshow_run({
      script_text: scriptText,
      image_paths: _slideshowImages,
      aspect_ratio: _q('slideshow-aspect-select').value,
    });
    if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
    return;
  }
  if (_runMode === 'short') {
```

(the rest of the existing `short` branch and the trailing documentary-mode code below it are unchanged.)

- [ ] **Step 7: Generalize `_resetProgress()`/`_setStage()` in `app.js`**

Replace:

```javascript
const STAGES = ['Script','Scenes','Audio','Keywords','Footage','Sync','Timeline','Done'];
const SHORT_STAGES = ['Script','TTS','Alignment','Footage','Assembly','Captions & Music','Mux'];

function _resetProgress() {
  _q('progress-title').textContent = 'Generating…';
  _q('log-area').innerHTML = '';
  _q('open-folder-btn').style.display = 'none';
  const isShort = _runMode === 'short';
  _q('stage-track').style.display = isShort ? 'none' : '';
  _q('shorts-stage-track').style.display = isShort ? '' : 'none';
  const stages = isShort ? SHORT_STAGES : STAGES;
  stages.forEach((_, i) => _setStage(i, 'pending'));
}

function _setStage(i, state) {
  const prefix = _runMode === 'short' ? 'short-stage-' : 'stage-';
```

with:

```javascript
const STAGES = ['Script','Scenes','Audio','Keywords','Footage','Sync','Timeline','Done'];
const SHORT_STAGES = ['Script','TTS','Alignment','Footage','Assembly','Captions & Music','Mux'];
const SLIDESHOW_STAGES = ['TTS','Assembly','Mux'];

function _resetProgress() {
  _q('progress-title').textContent = 'Generating…';
  _q('log-area').innerHTML = '';
  _q('open-folder-btn').style.display = 'none';
  _q('stage-track').style.display = (_runMode === 'short' || _runMode === 'slideshow') ? 'none' : '';
  _q('shorts-stage-track').style.display = _runMode === 'short' ? '' : 'none';
  _q('slideshow-stage-track').style.display = _runMode === 'slideshow' ? '' : 'none';
  const stages = _runMode === 'short' ? SHORT_STAGES : _runMode === 'slideshow' ? SLIDESHOW_STAGES : STAGES;
  stages.forEach((_, i) => _setStage(i, 'pending'));
}

function _setStage(i, state) {
  const prefix = _runMode === 'short' ? 'short-stage-' : _runMode === 'slideshow' ? 'slideshow-stage-' : 'stage-';
```

- [ ] **Step 8: Add `start_slideshow_run` and `browse_images` to `bridge.py`**

In `docu_studio/gui/bridge.py`, add the stage map and extend the final-index map. Replace:

```python
    _SHORTS_STAGE_MAP = {
        "script": 0, "tts": 1, "alignment": 2, "footage": 3,
        "assembly": 4, "caption": 5, "music": 5,
        "mux": 6, "done": 6, "complete": 6,
    }
    _FINAL_STAGE_INDEX_BY_MODE = {"doc": 7, "shorts": 6}
```

with:

```python
    _SHORTS_STAGE_MAP = {
        "script": 0, "tts": 1, "alignment": 2, "footage": 3,
        "assembly": 4, "caption": 5, "music": 5,
        "mux": 6, "done": 6, "complete": 6,
    }
    _SLIDESHOW_STAGE_MAP = {
        "tts": 0, "assembly": 1, "mux": 2, "done": 2, "complete": 2,
    }
    _FINAL_STAGE_INDEX_BY_MODE = {"doc": 7, "shorts": 6, "slideshow": 2}
```

In `_to_js_event`, replace:

```python
    def _to_js_event(self, event: object) -> dict | None:
        stage_map = self._SHORTS_STAGE_MAP if self._active_mode == "shorts" else self._STAGE_MAP
```

with:

```python
    def _to_js_event(self, event: object) -> dict | None:
        stage_map = (
            self._SHORTS_STAGE_MAP if self._active_mode == "shorts"
            else self._SLIDESHOW_STAGE_MAP if self._active_mode == "slideshow"
            else self._STAGE_MAP
        )
```

Immediately after the existing `start_shorts_run` method (before `def cancel_run`), add:

```python
    def start_slideshow_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "slideshow"
            from docu_studio.adapters.tts.factory import build_tts
            from docu_studio.slideshow.slideshow_runner import SlideshowRunner

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

            self._runner = SlideshowRunner(
                script_text=config.get("script_text", ""),
                image_paths=list(config.get("image_paths", [])),
                tts=tts,
                output_base=output_base,
                aspect_ratio=config.get("aspect_ratio", "9:16"),
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

Immediately after the existing `browse_folder` method (in the `# ── Filesystem ──` section), add:

```python
    def browse_images(self) -> list[str]:
        if not self._window:
            return []
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Image Files (*.jpg;*.jpeg;*.png;*.webp;*.bmp)", "All files (*.*)"),
        )
        return list(result) if result else []
```

(`webview.OPEN_DIALOG` matches the existing `webview.FOLDER_DIALOG` usage in `browse_folder` — both are deprecated in favor of `webview.FileDialog.*` in the installed pywebview version, but this keeps the file consistent with its own established convention rather than mixing two dialog-constant styles for no functional reason.)

- [ ] **Step 9: Bump the cache-busting version in `webview_app.py`**

In `docu_studio/gui/webview_app.py`, replace:

```python
the_url = str(WEB_DIR / "index.html") + "?v=10"
```

with:

```python
the_url = str(WEB_DIR / "index.html") + "?v=11"
```

- [ ] **Step 10: Restart the app and manually verify all three modes**

```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio
```

Verify by clicking through the UI:
1. Main screen shows three mode cards: Guided, Full Auto, Short/Reel (unchanged), and the new Slideshow card.
2. Documentary guided mode: topic input visible, duration row visible, start a run, confirm the existing 8-stage tracker still works exactly as before (byte-for-byte behavior check from the design spec).
3. Shorts mode: confirm topic/duration/captions/music/advanced rows and the 7-stage tracker still work exactly as before.
4. Slideshow mode: click the card, confirm topic row is hidden, images/script/aspect rows are visible, doc-duration/short-duration/aspect(short)/captions/music/advanced rows are all hidden. Click "Choose images…", pick 2-3 test images, confirm they appear in order with working ↑/↓/✕ controls. Type a short script. Click Start. Confirm the 3-stage tracker (TTS/Assembly/Mux) advances and the run completes with an output video.

- [ ] **Step 11: Commit**

```bash
git add docu_studio/gui/web/index.html docu_studio/gui/web/app.js docu_studio/gui/bridge.py docu_studio/gui/webview_app.py
git commit -m "feat(slideshow): wire Slideshow mode into the GUI additively"
```

---

### Task 8: Real-run verification and Phase 1 close-out

**Files:** none (verification only — no code changes expected; if a real run surfaces a bug, fix it in the relevant file from Tasks 1-7 and note it in the report below)

- [ ] **Step 1: Fresh full-suite run**

Run: `.venv/bin/python -m pytest -q --continue-on-collection-errors`
Expected: `24 failed, 478 passed, 1 error` (unchanged failed/error count from the pre-Task-1 baseline, all 36 new Slideshow tests passing).

- [ ] **Step 2: Real end-to-end Slideshow run, watched, not just logged**

```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio
```

Using 4-6 real test images (varied aspect ratios, to exercise the crop-to-target-aspect path) and a ~40-60 word script, run all three aspect ratios (9:16, 16:9, 1:1) at least once each. For each: **watch the rendered output video**, not just the "completed" status — confirm no visible pixel-stepping in the Ken Burns motion, no black bars/letterboxing artifacts from the crop step, narration audio is present and in sync with the video length, and the file plays cleanly start to finish with no concat glitches at segment boundaries.

- [ ] **Step 3: Confirm Documentary and Shorts are unaffected**

Run one real Documentary guided-mode generation and one real Shorts generation end-to-end (not just unit tests) to confirm the additive GUI/bridge changes didn't regress either existing mode — same verification discipline the design spec requires.

- [ ] **Step 4: Write the session handoff report**

Cover: which of the 36 new tests exist and pass, exact commit hashes for each task, current push status (not pushed — confirm with user before pushing), what's verified-by-eyes (the real Slideshow/Documentary/Shorts runs from Steps 2-3) vs verified-by-logs-only, any bugs found and fixed during the real run (expected, per the design spec's own prediction), and what's explicitly out of scope / open for Phase 2 (topic-based image fetch, LLM script generation) and Phase 3 (crossfade transitions, pan/rotation motion variety, captions, music) — each of which gets its own spec via the brainstorming skill before implementation starts.

- [ ] **Step 5: No commit for this task unless Step 2/3 surfaced a fix** — if it did, commit that fix separately with a message describing the real-run bug it addresses, mirroring how Shorts' own real-run bugs were committed individually.
