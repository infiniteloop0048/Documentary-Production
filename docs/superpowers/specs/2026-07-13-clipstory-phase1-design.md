# Clip Story Phase 1 — Design Spec

**Date:** 2026-07-13
**Status:** Approved
**Scope:** Phase 1 only — manual video upload with ordering, per-video trim in/out,
per-video own-script or LLM-flag, one coordinated LLM generation pass for flagged clips,
the three-layer duration-fit (script sizing → bounded atempo → halt-and-report), per-segment
assembly, hard-cut concat, final mux. No captions, no music, no crossfade transitions yet —
those are Phase 2, wired on top of `common/`'s already-built captions/ducking once Phase 1
is verified in a real run.

Clip Story is the fourth pipeline alongside Documentary, Shorts, and Slideshow. Unlike all
three of those (which fetch/generate disposable visual content and let script/TTS timing
set the pace), Clip Story takes the user's own uploaded video files as the fixed asset —
**duration authority flips**: each video's (trimmed) length sets the target duration, and
narration is fit into it, not the other way around. This is the one genuinely novel
algorithm in the feature and gets the most design and test attention.

## Standing constraints (from CLAUDE.md, unchanged)

- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files — new adapter files are
  fine), `history/`, `licensing.py`, or existing test files unless fixing an actual bug in
  them.
- Correct venv is `.venv/`, never `venv/`. Restart before testing any change:
  `pkill -f docu_studio 2>/dev/null && DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Confirm the current test baseline before starting (task doc states last known: 24
  pre-existing, unrelated failures, zero regressions post-extraction) via a fresh,
  isolated measurement — do not trust a number carried over from a prior session.
- Commit incrementally on a new branch (`clipstory-phase1`). Do not push without explicit
  go-ahead.
- Build on top of `docu_studio/common/` (resilient download, Jamendo music + cache, audio
  ducking, captions/ASS generation, ffmpeg SAR/pixfmt finalize). Do not write a sixth
  duplicate copy of anything already there.
- Bump the cache-busting `?v=N` in `webview_app.py` after any HTML/JS edit — current
  value confirmed by reading the file is `?v=12`, so this phase's GUI change bumps it to
  `?v=13`.

## Investigation findings

An Explore agent read the real source before this design was written (not the task doc's
assumptions about it). Key findings:

- **`docu_studio/common/`** currently has 5 modules: `resilient_download.py`,
  `music_jamendo.py`, `audio_ducking.py`, `captions.py`, `ffmpeg_finalize.py`. Shorts and
  Slideshow both consume them with the same calling convention: top-of-file import for
  always-used helpers (`finalize_filter`, `resilient_download`), **deferred (inside-function)
  import** for `captions`/`audio_ducking` in the assembly modules (used only when
  captions/music are enabled). Clip Story's assembly module matches this — Phase 1 doesn't
  import `captions`/`audio_ducking` at all (deferred to Phase 2).
- **TTS pace calibration** (`get_wpm`/`record_measurement`, EMA-blended, clamped
  `[90, 220]` WPM) exists today only in `docu_studio/shorts/shorts_tts_calibration.py` — it
  is genuinely reusable data (per-provider/voice measurements, not pipeline-specific) that
  was never promoted to `common/` because Slideshow never needed it (Slideshow uses a flat
  `SLIDESHOW_WPM = 150` constant with no calibration at all — confirmed nothing to
  consolidate there).
- **No existing "fit narration to a fixed duration window" logic anywhere.** Slideshow's
  `split_duration_evenly`/`crossfade_segment_durations` in `slideshow_assembly.py` solve the
  *opposite* direction (divide a known narration duration evenly across N images) and don't
  transfer. There is also **zero use of ffmpeg's `atempo` filter anywhere in this repo** —
  the "bounded pacing nudge" the task doc describes as "mirroring a problem already solved
  in Shorts" has no actual precedent; Shorts only speed-ramps *video* footage
  (`SPEED_RAMP_FACTOR`/`_MIN_SPEED_FACTOR`, video-only `setpts`, unbounded on the slow
  side) as a fallback-motion-detection workaround, which is a different mechanism for a
  different problem. Clip Story's atempo-based layer is new engineering, not a port.
- **No shared "call LLM for structured generation" helper.** Every pipeline builds its own
  call in `gui/bridge.py` via `adapters/llm/factory.py::build_llm(provider, key, model)` and
  then calls only `LLMProvider`'s public ABC methods (`generate_script`,
  `break_into_scenes`, ...). Shorts already sets the precedent of repurposing an existing
  public method (`break_into_scenes`) for a shape it wasn't originally written for, rather
  than editing `adapters/`. Clip Story follows the same discipline (see below).
- **`FFmpegWrapper.mux_audio_video`** (`media/ffmpeg_wrapper.py:115-139`) already does
  `-map 0:v:0 -map 1:a:0` explicitly, specifically because ffmpeg's auto-stream-selection
  would otherwise leak source footage audio into the mux. This means "mute the uploaded
  clip's original audio, narration only" (the Phase 1 decision — see below) requires **no
  new code**; reusing this inherited method as-is already does it.
- Slideshow's manual image list (`gui/web/app.js:244-322`) uses a plain JS array + up/down/
  remove buttons (no drag-and-drop, no thumbnail library) rendered from `file://` URLs — the
  pattern Clip Story's clip list mirrors, with per-item state extended to
  `{path, trimIn, trimOut, scriptText, useLlm}` and new numeric trim fields (no scrubber —
  see Decisions below).

## Decisions made during brainstorming (with rationale)

These were open questions the task doc didn't pin down; each was resolved explicitly
rather than left implicit:

1. **Original audio of uploaded clips: muted, narration only.** Achieved for free by
   reusing `mux_audio_video` unchanged (see investigation above). Ducking the original
   audio under narration, or a per-clip toggle, is explicitly out of scope for Phase 1.
2. **Trim UI: numeric in/out fields in seconds**, not a scrubber/timeline preview. Keeps
   Phase 1 frontend effort on the duration-fit algorithm (the actual risk) rather than new
   video-scrubber UI with no precedent in this codebase.
3. **Clip thumbnails: extracted poster frame via ffmpeg**, one fast frame-extract per
   upload (`ClipStoryFFmpeg.extract_poster_frame`), shown the same way Slideshow shows
   image thumbnails.
4. **Explicit review/edit step between narration text and TTS.** A "Generate Narration"
   action runs Layer 1 (word-count targeting) + the one coordinated LLM call for flagged
   clips, and shows every segment's text with its pace estimate in an editable box. A
   separate "Render" action only starts after this review step, so users can fix LLM output
   or shorten their own text before any TTS/ffmpeg work runs.
5. **TTS calibration promoted to `common/tts_calibration.py`.** `shorts_tts_calibration.py`
   moves there verbatim (mechanical rename + one import-line update in
   `shorts_script_gen.py`); both pipelines share one real-world measurement store. This
   gets the same real-E2E verification as every other extraction in this project (see
   Verification below) — not skipped because it looks mechanical.
6. **Coordinated LLM call: one crafted prompt through `generate_script`, parsed by
   delimiter** — no new `LLMProvider` ABC method, no edits to `adapters/`. The prompt
   encodes the *entire* ordered clip sequence: user-written clips appear as fixed,
   verbatim context (never regenerated), LLM-flagged clips appear as "fill this slot,
   target ~N words," and the model is instructed to separate its output per slot with a
   `===SEGMENT n===` delimiter. The response is split by that delimiter and mapped back
   only onto the flagged slots. If the parsed segment count doesn't match the expected
   count: one retry with a stricter prompt restating the delimiter format; still mismatched
   → hard-fail with expected-vs-found counts surfaced to the user. Never guess-split.
7. **Layer 3 (unrecoverable pacing gap) halts the whole render** with an exact numeric
   report, rather than skipping the offending clip and continuing. No partial-resume state
   machine exists anywhere in this codebase; building one for a rare edge case is scope
   creep for a first version of a brand-new algorithm.
8. **Output canvas: user picks 16:9 (1920×1080) or 9:16 (1080×1920) once, at project
   start.** Every clip is scaled+padded to that single canvas before concat, regardless of
   its native aspect ratio — necessary because, unlike Shorts (always vertical) or
   Slideshow (single aspect-ratio dropdown per project already), Clip Story's uploads can
   arrive in any mix of aspect ratios.

## Package structure

```
docu_studio/clipstory/
    clipstory_runner.py      # orchestrator entry point, ProgressEvent queue — mirrors
                              # shorts_runner.py's shape (event_queue, cancel_event, run()).
    clipstory_config.py      # ClipSpec(path, trim_in, trim_out, script_text,
                              # use_llm_generation) + ClipStoryConfig(topic, clips,
                              # tts_provider, tts_voice, llm_provider, llm_model,
                              # output_resolution, ...).
    clipstory_script_gen.py  # Layer 1: target_word_count(duration, wpm) (same formula as
                              # Shorts/Slideshow), estimated_seconds(word_count, wpm) for
                              # user-written pace display, coordinated multi-segment LLM
                              # prompt builder + delimiter parser (with retry-then-hard-fail).
    clipstory_pacing.py      # Layers 2-3, pure math, no I/O, no ffmpeg calls:
                              #   compute_ideal_speed_factor(actual, target) -> float
                              #   clamp_speed_factor(ideal, lo=0.85, hi=1.15) -> float
                              #   evaluate_fit(actual, target, lo=0.85, hi=1.15,
                              #                halt_tolerance=0.10) -> FitResult
                              #   plan_reconciliation(actual, target, epsilon=0.05)
                              #     -> ReconciliationPlan(action, adjustment_seconds)
                              # Fully unit-testable in isolation (see Testing).
    clipstory_ffmpeg.py       # class ClipStoryFFmpeg(FFmpegWrapper): adds
                              #   apply_atempo(audio_path, speed_factor, output_path)
                              #   normalize_clip(video_path, output_resolution, output_path)
                              #     — scale+pad+setsar+format via common.ffmpeg_finalize
                              #     .finalize_filter(...), re-encoded, applied to every clip
                              #   apply_reconciliation(audio_path, plan, target_duration,
                              #     output_path, fade_duration=0.3) — pad (apad) or
                              #     trim+afade-out, per plan.action
                              #   extract_poster_frame(video_path, timestamp, output_path)
                              # Reuses inherited trim_clip, mux_audio_video, concat_clips,
                              # get_duration unchanged.
    clipstory_assembly.py    # Orchestrates the full per-clip pipeline (see Data flow) and
                              # final concat + mux. Deferred imports of common.captions /
                              # common.audio_ducking are Phase 2 — not present in Phase 1.
```

**Shared-core change:** `docu_studio/shorts/shorts_tts_calibration.py` moves to
`docu_studio/common/tts_calibration.py` (same public API, no behavior change); update the
one import line in `docu_studio/shorts/shorts_script_gen.py` to point at the new location.

## Data flow

**Review step** (triggered by "Generate Narration," before any TTS/ffmpeg work):

1. GUI has collected: topic, output canvas (16:9/9:16), and an ordered clip list — each
   item `{path, trim_in, trim_out, script_text | flagged_for_llm}`.
2. For every clip: `target_duration_estimate = trim_out - trim_in` (simple arithmetic —
   no physical trim exists yet); `wpm = get_wpm(tts_provider, tts_voice, default=170)`
   (170 matches Shorts' existing default, same TTS stack); `target_words =
   target_word_count(target_duration_estimate, wpm)`.
3. One coordinated LLM call (via `generate_script` + delimiter parsing, decision 6 above)
   fills every `flagged_for_llm` clip's text, given the full sequence including fixed
   user-written segments as context.
4. Every clip's final text (LLM-filled or user-written) is shown with its pace estimate
   (`estimated_seconds(word_count(text), wpm)` vs. `target_duration_estimate`) in an
   editable box. Nothing renders until the user proceeds to Render.

**Render step** (triggered by "Render," per clip, in order):

1. `trim_clip(video, trim_in, trim_out - trim_in)` → `trimmed_video.mp4`.
2. `measured_target_duration = get_duration(trimmed_video.mp4)` — the **authoritative**
   target for the rest of this clip's pipeline (not the Review step's arithmetic estimate;
   ffmpeg trims aren't always frame-exact).
3. `normalize_clip(trimmed_video.mp4, output_resolution)` → `normalized_video.mp4` —
   mandatory for every clip, given heterogeneous upload encodings.
4. TTS on the reviewed/edited text → `raw_narration.mp3`; `actual_duration =
   get_duration(raw_narration.mp3)`.
5. `fit = evaluate_fit(actual_duration, measured_target_duration)`. If `fit.should_halt`:
   **stop the entire render**, report a per-clip table (filename, target, actual, ideal
   factor, clamped factor, resulting duration, residual %) across all clips processed so
   far plus the one that triggered the halt.
6. `apply_atempo(raw_narration.mp3, fit.applied_factor)` → `tempo_narration.mp3`.
7. `plan = plan_reconciliation(get_duration(tempo_narration.mp3),
   measured_target_duration, epsilon=0.05)`; `apply_reconciliation(...)` →
   `final_narration.mp3` (pad with trailing silence if short; trim-with-fade-out if long;
   no-op within epsilon). **Log every clip's numbers regardless of outcome** — ideal
   factor, applied factor, residual ratio, reconciliation action, adjustment seconds — not
   just halts.
8. `mux_audio_video(normalized_video.mp4, final_narration.mp3)` → `segment.mp4` (original
   clip audio already discarded per decision 1).
9. After all clips: hard-cut `concat_clips` across all `segment.mp4` files, final output
   routed through `common/ffmpeg_finalize`.

## GUI (Phase 1 scope only)

One new mode card, "Clip Story," added the same additive way Shorts and Slideshow were:
a new branch keyed off `_runMode`/`_active_mode` in `bridge.py`, a new
`start_clipstory_run` bridge method mirroring `start_shorts_run()`/
`generate_slideshow_script`, a new `CLIPSTORY_STAGES` array and stage-track div, cache-bust
bump `?v=12` → `?v=13`.

Renders only what's implemented in Phase 1:

- Topic text input.
- 16:9 / 9:16 output-canvas toggle (decision 8), set once per project.
- Multi-file **video** picker (`browse_videos()`, mirrors `browse_images()` with video
  extensions), ordered list with up/down/remove buttons (mirrors Slideshow's JS pattern,
  decision applies per-item state `{path, trimIn, trimOut, scriptText, useLlm}` instead of
  bare paths).
- Per-clip: extracted poster-frame thumbnail (decision 3), numeric trim-in/trim-out fields
  in seconds (decision 2) with the clip's total duration shown alongside, a script textarea
  OR an "LLM-generate" flag checkbox (mutually exclusive per clip).
- "Generate Narration" button (Review step) → per-clip editable text box + pace-estimate
  label, populated per Data flow above.
- "Render" button, enabled only after every clip has reviewed text — starts the Render
  step.
- On Layer 3 halt: a blocking panel showing the exact per-clip numbers (not a toast, not a
  log-only message) so the user can decide what to change before re-rendering.

Captions toggle, music toggle, crossfade-transition dropdown are **not rendered yet** —
Phase 2.

Verification requirement: after this GUI change, confirm Documentary, Shorts, and
Slideshow's existing flows are still byte-for-byte unchanged.

## Error handling

- **Layer 3 halt** → structured `ProgressEvent(stage="Error", ...)` carrying the full
  per-clip numeric breakdown described above.
- **LLM delimiter-parse mismatch** → one retry with a stricter prompt; still mismatched →
  hard-fail with expected-vs-found segment counts. Never guess-split.
- **Invalid trim range** (`trim_in >= trim_out`, or `trim_out` beyond the clip's actual
  duration) and **unreadable uploaded video** (ffprobe fails) → validated at input time
  (system boundary: upload/edit time), inline error in the clip list, blocks "Generate
  Narration"/"Render" until fixed.
- TTS/ffmpeg failures otherwise propagate through the existing runner error-surface
  pattern already used by `ShortsRunner`/`SlideshowRunner` — no new error-handling pattern
  invented.

## Testing

- `clipstory_pacing.py` — fully pure, table-driven unit tests, the highest-rigor target
  per the task doc:
  - `compute_ideal_speed_factor`: normal cases, `actual == target` (factor 1.0).
  - `clamp_speed_factor`: below/above/exactly-at each bound (0.85, 1.15).
  - `evaluate_fit`: (a) ideal within bounds → applied == ideal, ~0 residual, no halt;
    (b) clamped but residual ≤ 10% → no halt; (c) clamped and residual > 10% → halt;
    boundary case `residual_ratio == 0.10` exactly → no halt (trigger is strict `>`).
  - `plan_reconciliation`: shortfall beyond epsilon → `pad`; excess beyond epsilon →
    `trim_fade`; within epsilon either direction → `none`; boundary at exactly epsilon.
- `clipstory_script_gen.py` — `target_word_count`/`estimated_seconds` exact expected
  values for known WPM/duration pairs and rounding behavior; delimiter-parser with
  well-formed input, missing-delimiter input, and wrong-segment-count input (mocked LLM
  response — no real API call), confirming the retry-then-hard-fail path triggers
  correctly.
- `clipstory_ffmpeg.py` — golden filter-string assertions for `normalize_clip`'s
  scale/pad/SAR filter chain per output canvas (no real ffmpeg execution needed), same
  style as `test_shorts_ffmpeg.py`; `apply_reconciliation`'s pad-vs-trim-fade branch
  selection with subprocess mocked, matching this repo's existing ffmpeg-wrapper test
  convention.
- Orchestration test for `clipstory_assembly.py`/`clipstory_runner.py` with mocked
  TTS/ffmpeg calls, mirroring `test_shorts_assembly.py`'s structure — including a case
  that exercises a Layer 3 halt end-to-end (mocked durations chosen to force it) and a
  case that exercises Layer 2's atempo + reconciliation path.
- Baseline check: confirm the pre-existing failure/collection-error count on a fresh,
  isolated measurement before starting — do not carry over the "24" figure from the task
  doc without re-measuring.

## Verification requirement for the `tts_calibration.py` move

Because this touches Shorts (not just Clip Story), it gets the same real-E2E discipline as
every other extraction in this project: after moving the file and updating the import,
restart the app and run one real Shorts render end-to-end, confirming the calibration
JSON file still loads pre-existing data and still updates after the run — not a
lint/import-only check.

## Delivery checkpoint

After Phase 1 code is written and unit tests pass: kill and restart the app, then run a
real end-to-end Clip Story generation with two or three actual uploaded video files of
varying durations — including deliberately: one clip where the reviewed narration is
close to natural pace, one where it's short enough that Layer 2's atempo has to slow
narration down, and if feasible one that pushes far enough to trigger the Layer 3 halt on
purpose (verifying the halt path is real, not just logically sound). Extract and
personally inspect: cut points landing where trims were set, narration audibly fitting
each segment without absurd speed distortion, the reconciliation fade/pad being inaudible
or unobtrusive, and the actual per-clip numbers in the log for whichever clip invoked
Layer 2/3 — confirmed by checking the numbers, not by assuming success because the run
completed. Report back with what's verified-by-eyes vs. verified-by-logs-only before
Phase 2 (captions, music, crossfade transitions) gets its own spec.
