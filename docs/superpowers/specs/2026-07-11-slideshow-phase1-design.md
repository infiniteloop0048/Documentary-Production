# Slideshow Phase 1 — Design Spec

**Date:** 2026-07-11
**Status:** Approved
**Scope:** Phase 1 only — manual image upload + own-script narration + basic Ken Burns +
hard-cut assembly. No topic-based image fetch, no LLM script generation, no captions, no
music, no transition variety, no pan/rotation motion variants. Those are separate specs
for Phase 2 and Phase 3, written after this phase is built and verified in a real run.

This is the first of what will likely be 3 specs (mirroring how Shorts itself was built
in S1→S3 stages) for the overall "Image-to-Video Slideshow" feature requested alongside
the existing Documentary and Shorts pipelines.

## Standing constraints (from CLAUDE.md, unchanged)

- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files), `history/`,
  `licensing.py`, or existing test files, unless fixing an actual bug in them.
- Correct venv is `.venv/`, never `venv/`.
- Kill and restart the app before testing any change (`pkill -f docu_studio`).
- Add version-marker log lines to new pipeline stages.
- Bump the cache-busting `?v=N` in `webview_app.py` after any HTML/JS edit — **current
  value confirmed by investigation is `?v=10`**, so this phase's GUI change bumps it to
  `?v=11`.
- Commit incrementally. Do not push without explicit go-ahead.

## Investigation findings (grounding this design in actual code, not the original
handoff doc's memory of it)

An Explore agent read the real Shorts source before this design was written. Key
confirmations and discrepancies against the original task doc:

- **Confirmed accurate:** the Ken Burns zoompan technique (`shorts_ffmpeg.py:269-317`) —
  4x lanczos upscale (`scale=4320:-2:flags=lanczos`) before `zoompan`, non-accumulating
  zoom expression (`1+{zoom_delta}*on/{denom}`), and the SAR/pixfmt finalize step
  (`setsar=1,format=yuv420p`, `_SAR_PIXFMT_SUFFIX`, `shorts_ffmpeg.py:41`) that fixed the
  documented "SAR parameters do not match" concat-crash bug.
- **Confirmed accurate:** the resilient-downloader pattern in `shorts_footage_download.py`
  (session reuse, browser UA, `(10, 30)` connect/read timeouts, capped 3-attempt backoff
  with jitter on `ConnectionError`/`Timeout`/retriable 5xx/429 only, same-host pacing).
- **Confirmed accurate:** the sentence-scoped "own pool → topic fallback → never borrow a
  neighbor's" assignment rule, implemented in `shorts_assembly.py:136-230` and enforced at
  the segment level by `plan_sentence_scoped_cuts()` in `shorts_sentence_cuts.py`.
- **Discrepancy — Jamendo client_id:** the task doc referenced a baked-in default client_id
  (`58ae1ef1`). This does **not exist** anywhere in the repo. `JamendoMusicProvider`
  requires the caller to supply a client_id, sourced exclusively from user-entered keyring
  storage (`config/key_cache.py`, GUI Settings → Music). Not relevant to Phase 1 (no music
  yet), but Phase 3's spec must not assume a default exists.
- **Discrepancy — coupling assessment:** the task doc's Option A (extract a shared
  `common/segment_assembly.py` with a swappable "produce visual for this segment" strategy)
  is riskier than assumed. `_build_segment()` in `shorts_assembly.py:319-403` interleaves
  genuinely video-specific steps (ffprobe duration, motion-window detection, speed-ramp,
  clip trim) with the reusable tail (vertical-convert → Ken Burns → concat/caption/music/mux).
  A clean strategy-pattern swap is possible but requires deliberate interface design, not a
  mechanical extraction. This informed the "defer extraction per-phase" decision below.

## Architecture decision

**Defer all `common/` extraction to the phase that actually needs each shared piece,
instead of front-loading a Phase 0 refactor.**

Tracing through what Phase 1 actually needs revealed it doesn't touch any of the shared
infrastructure the original task doc assumed it would: no word-timing tiers, no
`sentence_spans()`, no resilient downloader, no music providers. Phase 1 only needs total
narration duration (one `ffprobe` call) split evenly across the given images, plus the Ken
Burns *technique* reimplemented with generalized output dimensions (Shorts hardcodes
1080x1920 vertical; Slideshow needs 9:16/16:9/1:1).

Extracting code into `common/` now, before anything actually depends on the shared version,
would be speculative — exactly what CLAUDE.md's Simplicity First principle warns against.
Instead:

- **Phase 1 (this spec):** zero changes to `shorts/`. Slideshow ships as a fully
  self-contained `docu_studio/slideshow/` package, reusing only what's already
  pipeline-agnostic and shared today (the TTS adapter factory, the LLM adapter factory —
  neither is Shorts-specific).
- **Phase 2 (future spec):** when topic-based image fetch is built, extract the
  resilient-downloader pattern into `common/resilient_downloader.py` at that point,
  generalized for image URLs, and point `shorts_footage_download.py` at it too (zero
  behavior change to Shorts, verified via real run before Slideshow code lands on top).
- **Phase 3 (future spec):** when captions and music are built, extract `word_timing.py`,
  `sentence_spans.py`, and `music_providers.py`/ducking into `common/` at that point, for
  the same reason.

Each extraction stays small, scoped, and immediately justified by the phase using it. This
minimizes risk to Shorts at every step and avoids moving code whose shared shape isn't
actually known until a second real caller (Slideshow) exists to prove it out.

## Package structure

```
docu_studio/slideshow/
    slideshow_runner.py     # orchestrator entry point — mirrors ShortsRunner's shape
                             # (event_queue, cancel_event, _final_video_path,
                             # _project_folder, run())
    slideshow_script.py     # Phase 1: wraps user-supplied text verbatim. Splits into
                             # sentences only for logging/validation — sentence count is
                             # not used for image timing in Phase 1 (see Data flow).
                             # Reimplements the ~3-line regex sentence splitter rather
                             # than importing shorts_script_gen, to keep zero coupling
                             # to shorts/ for one trivial function.
    slideshow_images.py     # Phase 1: manual ordered image list only. Validates each
                             # path exists and is a readable image, rejects an empty
                             # list. Topic-based fetch is a stub raising
                             # NotImplementedError("Phase 2") — not wired into the GUI.
    slideshow_motion.py     # Ken Burns config. Phase 1 supports classic in/out only
                             # (center-in zoom, center-out zoom). Pan/rotation/mixed
                             # variants are Phase 3.
    slideshow_ffmpeg.py     # SlideshowFFmpeg class. Ken Burns filter generalized to
                             # take output width/height as parameters. Same technique as
                             # Shorts: 4x lanczos upscale before zoompan, non-accumulating
                             # zoom expression, setsar=1,format=yuv420p finalize (own
                             # _finalize_filter, same fix, new file — not imported from
                             # shorts_ffmpeg.py, since that class hardcodes vertical
                             # dimensions). Hard-cut concat only (ffmpeg concat demuxer).
    slideshow_assembly.py   # audio-first: TTS synthesize narration -> ffprobe total
                             # duration -> split duration evenly across N images (in
                             # given order) -> per-image Ken Burns segment -> concat ->
                             # mux narration audio over video.
```

No `docu_studio/common/` package is created in this phase.

## Data flow (Phase 1)

1. GUI collects: ordered image file paths, script text, aspect ratio (9:16/16:9/1:1),
   optional target duration.
2. `slideshow_runner` synthesizes narration audio via the existing TTS adapter factory
   (already shared infrastructure, not Shorts-specific — no reuse decision needed).
3. `FFmpegWrapper().get_duration(audio_path)` gets total narration duration — this is the
   video's total duration (audio-first, per the original requirement).
4. `slideshow_assembly` divides that duration evenly across the N images in the user's
   given order: `segment_duration = total_duration / N`, with the last segment absorbing
   any rounding remainder so segments sum exactly to the total (same tiling approach
   `sentence_spans()` uses in Shorts, reimplemented locally since it's a few lines and the
   two duration-splitting problems aren't identical enough to share yet — Shorts splits by
   word-timestamp-derived sentence boundaries, Slideshow splits by even image count).
5. Each image → `SlideshowFFmpeg.apply_ken_burns(image_path, out_wh, duration, direction)`
   → one `.mp4` segment.
6. Concat segments (hard cut, ffmpeg concat demuxer) → mux narration audio over the result
   → final output written via the existing `output/project_folder.py` (already shared,
   pipeline-agnostic).

This intentionally skips `sentence_spans()`, word-timing, and sentence-scoped pool
assignment entirely — those solve a problem (aligning per-sentence narration to
per-sentence *searched* image results) that doesn't exist yet when there's one flat,
manually-ordered image list and no topic search. That logic becomes relevant in Phase 2.

## GUI (Phase 1 scope only)

One new mode card, "Slideshow," in `index.html`, wired the same additive way Shorts was
added: a third `if/else` branch keyed off `_runMode`/`_active_mode` (currently `"doc"` /
`"shorts"` in `bridge.py`, adding `"slideshow"`), a new `start_slideshow_run` bridge
method mirroring `start_shorts_run()`, a new `SLIDESHOW_STAGES` array and
`#slideshow-stage-track` div mirroring `#shorts-stage-track`, and the cache-bust bump from
`?v=10` to `?v=11`.

Phase 1 renders only what's implemented — no half-built toggles, per CLAUDE.md's "no
half-finished implementations":

- Multi-file image picker with an ordered thumbnail list (add / remove / drag-reorder).
- Script textarea (free text, required, non-empty).
- Aspect ratio dropdown (9:16 / 16:9 / 1:1).
- Optional target-duration field (if set, this is advisory only in Phase 1 since duration
  is narration-driven; if empty, duration is purely however long the TTS narration runs).
- Start button.

Topic-based image source toggle, LLM script generation toggle, motion-style variety,
transition dropdown, captions toggle, and music toggle are **not rendered yet** — added
additively in the Phase 2/3 GUI updates.

Verification requirement: after this GUI change, confirm the existing Documentary
(`start_run`) and Shorts (`start_shorts_run`) flows are still byte-for-byte unchanged,
same verification discipline Shorts used against Documentary.

## Error handling

- Fail fast with a clear message for: empty image list, unreadable/corrupt image file,
  empty script text.
- TTS/ffmpeg failures propagate through the existing runner error-surface pattern already
  used by `ShortsRunner`/`PipelineRunner` (no new error-handling pattern invented).
- Ken Burns ffmpeg failures include the segment index (which image) in the error message
  for debuggability.

## Testing (Phase 1)

- `slideshow_ffmpeg.py`: golden filter-string assertions per aspect ratio for the Ken
  Burns expression (no real ffmpeg execution needed), same style as `test_shorts_ffmpeg.py`.
- `slideshow_assembly.py`: pure duration-split function — N images → N segment durations
  summing exactly to total duration, remainder handling, single-image edge case.
- `slideshow_images.py`: validation logic (rejects missing/unreadable file, rejects empty
  list, preserves given order).
- Orchestration test for `slideshow_runner`/`slideshow_assembly` with mocked TTS/ffmpeg
  calls, mirroring `test_shorts_assembly.py`'s structure.
- Baseline check: confirm the pre-existing failure/collection-error count on a fresh,
  isolated measurement before starting — do not trust a number carried over from a prior
  session (the handoff notes flag this was previously disputed between 17 and 24 failures).

## Delivery checkpoint

After Phase 1 code is written and unit tests pass: kill and restart the app
(`pkill -f docu_studio && DISPLAY=:1 .venv/bin/python -m docu_studio`), run a real
Slideshow generation end-to-end with a handful of test images and a short script, and
**watch the rendered output** before declaring Phase 1 done — logs and tests verify code
correctness, not that the video actually looks right. Report back with what's
verified-by-eyes vs verified-by-logs-only before Phase 2 (topic-based fetch + LLM script)
gets its own spec.
