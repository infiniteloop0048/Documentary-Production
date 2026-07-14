# Shorts Aspect Ratio Choice — Design Spec

**Date:** 2026-07-14
**Status:** Approved
**Scope:** Task 1 of the "Shorts: Aspect Ratio, Audio Lead-in Bug, Subtitle Bug,
Scene/Narration Audit" session — build task only. Tasks 2-4 (audio lead-in bug, subtitle
bug, scene/narration audit) are investigate-and-report-back only and are out of scope for
this branch.

## Standing constraints (from CLAUDE.md, unchanged)

- Do not touch `pipeline/`, top-level `runner/`, existing files in `adapters/`, `history/`,
  `licensing.py`, or existing test files unless fixing a genuine bug in them.
- Correct venv is `.venv/`, never `venv/`. Kill-and-restart discipline before testing —
  never test against a stale running process:
  `pkill -f docu_studio 2>/dev/null; DISPLAY=:1 .venv/bin/python -m docu_studio`.
- New worktree + branch for this task only (`shorts-aspect-ratio`), independent of the other
  three tasks in this session. Review-before-merge, no push to origin without explicit
  go-ahead.
- This is the Shorts pipeline only. Any change to `docu_studio/common/` must be strictly
  additive (new optional parameters), never a modification of existing default behavior,
  since `common/` is shared with Slideshow and Clip Story — both out of scope for this
  session.
- Bump the cache-busting `?v=N` query string in `docu_studio/gui/webview_app.py` after any
  HTML/JS edit — confirmed current value by reading the file: `?v=14`. This change bumps it
  to `?v=15`.

## Investigation findings (read from real source, not assumed)

- **Shorts is hardcoded vertical today.** `SHORTS_WIDTH = 1080` / `SHORTS_HEIGHT = 1920` are
  defined as module-level constants in **two** places —
  `docu_studio/shorts/shorts_config.py` and `docu_studio/shorts/shorts_ffmpeg.py` — and every
  ffmpeg-facing method in `ShortsFFmpeg` (`vertical_convert`, `apply_ken_burns`,
  `generate_punch_card`) reads those module constants directly rather than accepting
  width/height as parameters. `ShortsConfig` (`shorts_config.py`) has no `aspect_ratio`
  field at all.
- **Slideshow already has the exact pattern to mirror.** `slideshow_config.py`:
  `SLIDESHOW_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "16:9":
  (1920, 1080), "1:1": (1080, 1080)}`, `SLIDESHOW_DEFAULT_ASPECT = "9:16"`,
  `SlideshowConfig.aspect_ratio: str = SLIDESHOW_DEFAULT_ASPECT` validated in
  `__post_init__` against the dict's keys, plus an `output_dimensions` property. Slideshow's
  `SlideshowFFmpeg.apply_ken_burns_image` already takes `out_width`/`out_height` as
  parameters (unlike Shorts' `apply_ken_burns`, which hardcodes them) — confirmed by reading
  both files side by side.
- **`common/ffmpeg_finalize.py` is shared but dimension-agnostic.** It only appends
  `setsar=1,format=yuv420p` as the last step of a filter chain; it has no awareness of
  width/height at all. This change requires **zero modification** to this file — Shorts
  keeps calling `finalize_filter()` exactly as it does today, just with a different
  target-dimension filter chain built around it.
- **Captions are already fully generalized — zero change needed.** `common/captions.py`'s
  `write_ass_file(timestamps, ass_path, out_width, out_height, ...)` already takes
  width/height as parameters and sets `PlayResX`/`PlayResY` to those values. ASS/libass
  scales font size and margins relative to `PlayResX`/`PlayResY`, not absolute pixels, so a
  `Fontsize=64` line already renders correctly at 1080x1920, 1920x1080, or 1080x1080 alike —
  this is proven today by Slideshow using this exact module across all 3 aspect ratios
  already. Shorts' call site (`shorts_assembly.py`) just needs to pass the *chosen* output
  dimensions instead of the hardcoded `SHORTS_WIDTH`/`SHORTS_HEIGHT` import.
- **Footage fetch is orientation-agnostic already.** `_collect_clips_per_sentence` and
  `_collect_clips` in `shorts_assembly.py` search stock-footage providers by text query only
  — there is no width/height/aspect filtering anywhere in the search path. The *only* place
  vertical framing is assumed is the post-download crop step, `ShortsFFmpeg.vertical_convert`
  (hardcoded target 1080x1920). Generalizing that one method's target dimensions is
  sufficient; no change to the fetch/search/download path is needed.
- **`choose_crop_strategy(source_width, source_height)` in `shorts_cuts.py` stays
  unchanged — deliberate decision, confirmed with the user.** It picks `center_crop` vs.
  `blur_pad` by comparing the *source* clip's own aspect ratio against a fixed 16:9
  baseline (`_BASELINE_ASPECT = 16/9`) — this is a source-classification heuristic ("is this
  an unusually wide/anamorphic shot that a straight center-crop would butcher"), not a
  function of the chosen *target* aspect. It behaves sensibly regardless of which of the 3
  target aspects is selected, so no target-aware rework is in scope here. (Noted as the one
  judgment call in this design; flagged to and approved by the user during brainstorming.)
- **GUI wiring precedent already exists end-to-end for Slideshow**, giving an exact template:
  `index.html` has `<select id="slideshow-aspect-select">` with the 3 `<option>`s;
  `app.js`'s `startConfig()` toggles `#slideshow-aspect-row` display by mode, and its submit
  handler reads `_q('slideshow-aspect-select').value` into the `aspect_ratio` field of the
  `start_slideshow_run` payload; `gui/bridge.py`'s `start_slideshow_run` does
  `config.get("aspect_ratio", "9:16")` and forwards it into `SlideshowRunner(...)`.
  Shorts' config screen currently has a **static, non-interactive** `#aspect-row` div reading
  "9:16 vertical · 1080 × 1920 (fixed)" — this is what gets replaced with a real `<select>`.

## Design

### 1. `docu_studio/shorts/shorts_config.py`

Add, mirroring `slideshow_config.py` exactly:

```python
SHORTS_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
SHORTS_DEFAULT_ASPECT = "9:16"
```

`ShortsConfig` gains `aspect_ratio: str = SHORTS_DEFAULT_ASPECT`, validated in
`__post_init__` against `SHORTS_ASPECT_DIMENSIONS` (same error-message shape Slideshow
uses), plus an `output_dimensions` property returning
`SHORTS_ASPECT_DIMENSIONS[self.aspect_ratio]`. The existing `SHORTS_WIDTH`/`SHORTS_HEIGHT`
module constants stay as-is (they're `SHORTS_ASPECT_DIMENSIONS["9:16"]`'s values, and nothing
outside this file needs them removed — see below for why `shorts_ffmpeg.py`'s copies do get
removed).

Default aspect ratio is `"9:16"`, matching current behavior exactly — a user who never
touches the new setting gets an identical output to today.

### 2. `docu_studio/shorts/shorts_ffmpeg.py`

Parameterize the three methods that currently read the module-level `SHORTS_WIDTH`/
`SHORTS_HEIGHT` constants directly, replacing them with `out_width: int, out_height: int`
parameters:

- `vertical_convert(input_path, output_path, strategy, out_width, out_height)`
- `apply_ken_burns(input_path, output_path, duration, direction, pan, out_width, out_height)`
- `generate_punch_card(output_path, text, duration, out_width, out_height)`

No default values on the new parameters — both call sites (`shorts_assembly.py`) are being
updated in this same change, so there's no other caller that would break, and an
unparameterized call silently falling back to 1080x1920 would be a footgun for any future
caller.

The module-level `SHORTS_WIDTH = 1080` / `SHORTS_HEIGHT = 1920` constants in this file become
unused once the three methods above stop referencing them (this file's only two other uses —
`_PUNCH_CARD_BG`/`_PUNCH_FONT_NAME`/etc. — are unrelated styling constants, unaffected). Per
project convention (remove what your own change makes unused), these two lines are deleted
from `shorts_ffmpeg.py`. `shorts_config.py`'s copies are untouched — they remain the "9:16"
entry's canonical values via `SHORTS_ASPECT_DIMENSIONS`.

### 3. `docu_studio/shorts/shorts_assembly.py`

- `assemble_short(...)` gains an `output_dimensions: tuple[int, int]` parameter.
- `_build_segment(...)` gains the same parameter, threaded into its `vertical_convert` and
  `apply_ken_burns` calls (replacing the implicit module-constant use).
- The punch-card render call (`ffmpeg.generate_punch_card(...)`) passes
  `output_dimensions`.
- The `write_ass_file(timestamps, ass_path, SHORTS_WIDTH, SHORTS_HEIGHT, ...)` call is
  changed to pass `*output_dimensions` (or the unpacked width/height) instead of the
  hardcoded import; the `from docu_studio.shorts.shorts_config import SHORTS_HEIGHT,
  SHORTS_WIDTH` import is removed since it becomes unused.

### 4. `docu_studio/shorts/shorts_runner.py`

`ShortsRunner.__init__` gains `aspect_ratio: str = "9:16"`, passed into the `ShortsConfig(...)`
construction. `_execute()` passes `self.config.output_dimensions` into `assemble_short(...)`.

### 5. `docu_studio/gui/bridge.py`

`start_shorts_run` reads `aspect_ratio = config.get("aspect_ratio", "9:16")` and passes it
into `ShortsRunner(...)` — identical shape to the existing `start_slideshow_run` handling.

### 6. GUI: `docu_studio/gui/web/index.html` + `app.js`

- Replace the static `#aspect-row` div (currently a disabled-looking hint,
  `index.html` ~line 272-276) with a real `<select id="shorts-aspect-select">` offering the
  same 3 options as `#slideshow-aspect-select`, defaulting to `9:16` (selected first,
  matching current behavior). Visibility toggling (`display: mode === 'short' ? '' : 'none'`
  in `startConfig()`) already exists for `#aspect-row` and needs no change — only the
  row's *contents* change from a static hint to an interactive `<select>`.
- `app.js`'s short-run submit handler (the `if (_runMode === 'short')` block that calls
  `start_shorts_run`) gains `aspect_ratio: _q('shorts-aspect-select').value` in the payload
  object, mirroring the Slideshow submit handler's `aspect_ratio: _q('slideshow-aspect-select').value`.
- Bump `?v=14` → `?v=15` in `webview_app.py`.

### Non-goals / explicitly unchanged

- `choose_crop_strategy` in `shorts_cuts.py` — see investigation findings above.
- `common/ffmpeg_finalize.py`, `common/captions.py`, `common/audio_ducking.py` — no changes;
  all three are already dimension-agnostic or already parameterized.
- Footage search/fetch (`_collect_clips`, `_collect_clips_per_sentence`) — no aspect-aware
  filtering added; stock footage is fetched identically regardless of target aspect, then
  cropped to fit at the existing per-segment crop step.

## Testing

Extend existing test files (no rewrites, following existing conventions in each):

- `tests/unit/test_shorts_config.py` — `aspect_ratio` field default, valid/invalid values,
  `output_dimensions` property for all 3 ratios.
- `tests/unit/test_shorts_ffmpeg.py` — `vertical_convert`, `apply_ken_burns`,
  `generate_punch_card` invoked with each of the 3 target dimension pairs; assert the
  constructed ffmpeg command/filter strings contain the correct width/height (matching this
  file's existing assertion style, likely mocked `subprocess.run`).
- `tests/unit/test_shorts_assembly.py` — `assemble_short`/`_build_segment` correctly thread
  a non-default `output_dimensions` through to the `ShortsFFmpeg` calls and
  `write_ass_file`.

## Verification (before calling this task done)

Real E2E render — actual footage fetch, actual TTS, actual ffmpeg, no mocks — for **all
three** aspect ratios, run from a freshly restarted app process (kill any stale
`docu_studio` process first). For each of the 3 outputs:

1. `ffprobe` the final MP4: confirm exact width/height match the selected aspect ratio's
   `SHORTS_ASPECT_DIMENSIONS` entry, and `sample_aspect_ratio` is exactly `1:1` (clean SAR,
   no concat-rejection risk).
2. Extract at least one frame (`ffmpeg -ss ... -frames:v 1`) from each output and inspect it
   by eye to confirm the crop/frame looks correct for that orientation (no unexpected
   letterboxing, no obviously wrong crop).
3. Confirm the default (untouched setting) run still produces an identical-shaped 9:16
   1080x1920 output, to prove the default-preserving requirement holds.

## Out of scope for this branch

Tasks 2 (audio lead-in bug), 3 (subtitle bug), and 4 (scene/narration audit) from the parent
session are investigate-and-report-back only, on separate worktrees/branches, and are not
touched here.
