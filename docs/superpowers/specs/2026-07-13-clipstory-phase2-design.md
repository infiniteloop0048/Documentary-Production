# Clip Story Phase 2 — Design Spec

**Date:** 2026-07-13
**Status:** Draft — pending review
**Scope:** Phase 2 only — captions, background music + ducking, crossfade transitions,
all additive/default-off on top of Phase 1's uploaded-video/duration-authoritative
pipeline. No new duration-fit algorithm work; Phase 1's three-layer fit is untouched.

## Standing constraints (from CLAUDE.md, unchanged)

- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files — new adapter files are
  fine), `history/`, `licensing.py`, or existing test files unless fixing an actual bug in
  them.
- Correct venv is `.venv/`, never `venv/`. Restart before testing any change:
  `pkill -f docu_studio 2>/dev/null && DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Baseline reconfirmed fresh at the start of this phase (2026-07-13): **640 passed, 24
  failed**, plus one pre-existing collection error
  (`tests/integration/test_edge_tts_adapter.py` imports
  `docu_studio.adapters.tts.edge_tts_adapter`, a module that has never existed in this
  repo — unrelated to Clip Story, excluded from the run to get a clean count). Matches the
  task doc's stated baseline exactly.
- New worktree/branch `clipstory-phase2`, same review-before-merge pattern as every prior
  phase. Commit incrementally, do not push without explicit go-ahead.
- Bump the cache-busting `?v=N` in `webview_app.py` after any HTML/JS edit — current value
  confirmed by reading the file is `?v=13`, so this phase's GUI change bumps it to `?v=14`.

## Investigation findings

An Explore agent read the real source before this design was written. Key findings, and
where they change the task doc's assumptions:

- **Captions, ducking, and SAR-finalize are genuinely shared** and already consumed by
  Slideshow via deferred (inside-function) imports:
  `common/captions.py` (`WordTiming`, `estimate_word_timestamps`, `write_ass_file`),
  `common/audio_ducking.py` (`build_ducking_filtergraph`), `common/ffmpeg_finalize.py`
  (`finalize_filter`). All are pure functions/string-builders — no subprocess calls live in
  `common/` itself; each pipeline's own `*_ffmpeg.py` does the actual ffmpeg invocation.
  **Crossfade did NOT make it into `common/`** — confirmed by grep across the whole repo:
  `xfade`/`crossfade` logic exists only in `docu_studio/slideshow/slideshow_ffmpeg.py`
  (`concat_segments_with_xfade`) and `slideshow_assembly.py`
  (`crossfade_segment_durations`). The shared-core design spec explicitly scoped it out
  ("Slideshow-only, no Shorts duplicate to extract against" — never a shared-core
  candidate). **Clip Story's crossfade is new engineering, following Slideshow's technique,
  not an import.**
- **Music's local-folder provider is deliberately NOT unified** either — Shorts' and
  Slideshow's "local" concepts differ (bundled manifest vs. user-browsed folder), a
  decision already made during the shared-core extraction. Clip Story writes its own thin
  `clipstory_music.py`, copying Slideshow's `LocalFolderMusicProvider` +
  `resolve_music_track()` shape (folder scan, provider → local-folder → `None` fallback,
  never raises), while reusing `common/music_jamendo.py`'s `JamendoMusicProvider` and
  `TrackCandidate` as-is (100% shared, zero changes needed).
- **"Defaults to Jamendo if a key is cached" is not an existing runtime convention
  anywhere** — this was a task-doc assumption that doesn't hold up. Grepped
  `config/key_cache.py`, `config/settings.py`, and `gui/bridge.py`: Slideshow's
  `music_provider` default is a plain `config.get("music_provider", "jamendo")` static
  string, and the GUI's `<select>` just lists Jamendo first in the HTML (static ordering,
  not a runtime branch on cache state). **Decision: Phase 2 mirrors Slideshow's actual
  behavior exactly** (static `"jamendo"` default, Jamendo listed first in the dropdown) —
  it does not invent new "check the key cache and pick a default" logic that would make
  Clip Story behave differently from Slideshow for no product reason.
- **No TTS adapter in this codebase provides word-level timestamps** — confirmed on all
  three (`gtts_adapter.py`, `elevenlabs_adapter.py`, `deepgram_adapter.py`); `TTSProvider`'s
  ABC contract is `synthesize(text, path) -> float` (duration only). Shorts has a
  Whisper-based Tier-2 forced-alignment fallback (`shorts_alignment.py`) for higher
  accuracy, but it was never promoted to `common/`, and Slideshow's own Phase 3 explicitly
  chose not to depend on it (no new runtime dependency/model download for captions).
  **Decision: Clip Story captions use `common.captions.estimate_word_timestamps` only**
  (character-length-weighted Tier-3 estimate), same as Slideshow — consistent product
  behavior, zero new dependencies, and this is genuinely a zero-new-code reuse rather than
  a gap. Whisper-based alignment stays an explicit non-goal, matching Slideshow Phase 3's
  own precedent.
- **The real design fork: Clip Story mixes narration into each segment early
  (`mux_audio_video` runs per-clip, before concat), while Slideshow keeps narration
  entirely separate from video until the very last step.** This matters specifically for
  crossfade: Slideshow's `concat_segments_with_xfade` is video-only because Slideshow's
  segments never have audio muxed in yet. If Clip Story's crossfade also went video-only,
  concatenating each clip's *already-muxed* narration audio separately afterward would
  desync it from the video the instant a transition overlaps two segments (video shrinks
  by `transition_duration` at each cut; a naive audio concatenation wouldn't shrink to
  match). **Resolution, decided here:** Clip Story's crossfade concat operates on the
  already-AV-muxed segment files directly, chaining ffmpeg's `xfade` (video) and
  `acrossfade` (audio) filters together in one `filter_complex`, so video and audio shrink
  by the same overlap at every cut and stay in sync by construction — no restructuring of
  Phase 1's per-clip mux-then-concat order is needed. See §3 below.
- **Unlike Slideshow, Clip Story's crossfade legitimately shortens total output duration**
  by `(n-1) × transition_duration` relative to the sum of per-clip trims. Slideshow has to
  *preserve* total duration under crossfade because a single upstream narration duration is
  the thing being divided across segments (`crossfade_segment_durations` inflates segment
  lengths to compensate). Clip Story has no such single target — each clip's target
  duration is its own physical trim, already fully resolved and reconciled before concat
  ever runs. A crossfade genuinely eating a fraction of a second at each cut is expected,
  ordinary crossfade behavior here, not a bug to compensate for.
- Two Minor items from the Phase 1 report sit inside files this phase already touches
  (`clipstory_ffmpeg.py`), so both are in scope per the task's opportunistic-cleanup rule
  (§2d): (a) `apply_reconciliation`'s `"none"` branch does a bare `shutil.copy` with no
  `try/except`, so a copy failure raises a raw `OSError` instead of the `FFmpegError`
  every other branch of this method (and every other method in the class) raises — an
  inconsistent error contract for callers; (b) `concat_segments`'s filter_complex
  re-scales every segment to the output canvas even though `normalize_clip` already scaled
  each one to that exact resolution — a redundant re-encode pass on every hard-cut run.
  The GUI's narration-review innerHTML item (`app.js` line 424-427) is in a *different*
  region of `app.js` than this phase's new config-time controls — not the same
  neighborhood, left deferred and called out in the final report rather than silently
  fixed or silently skipped.

## Decisions made during brainstorming (with rationale)

1. **Captions burn per-clip, before concat — not once over the whole assembled video.**
   The task explicitly requires captions to stay within each clip's own segment span and
   never drift across a hard cut. Burning per-clip, using that clip's own final
   (post-reconciliation) narration duration and its own reviewed `script_text`, makes this
   true by construction — there is no cross-clip timeline for captions to drift across in
   the first place. Insertion point: after `normalize_clip`, before `mux_audio_video`
   (captions burn onto the video-only normalized clip, mirroring Slideshow's
   video-only-then-mux ordering, just per-clip instead of per-whole-video).
2. **Music mixes once, over the final assembled output — not per-clip.** A background bed
   is a whole-video concept; ducking it under a stitched-together, potentially crossfaded
   narration track only makes sense as one pass at the end, exactly mirroring Slideshow's
   placement (resolved before assembly starts, applied as the very last step before final
   mux).
3. **Crossfade concat operates directly on AV-muxed segments** using chained
   `xfade`+`acrossfade` (see investigation above) rather than restructuring Phase 1's
   per-clip audio-mux-then-concat order. This is the smallest change that keeps video/audio
   sync correct under overlap, and it means the hard-cut path (`concat_segments`, unchanged
   apart from the redundant-scale cleanup) needs zero structural changes.
4. **`transition_duration` fixed at 0.5s, not user-configurable** — matches Slideshow
   Phase 3's own choice (same rationale: keep the option surface minimal for a first pass).
5. **Crossfade requires at least 2 clips and every clip's measured duration must exceed
   `transition_duration`** (else the xfade `offset=` math goes negative/invalid for that
   pair). Rather than silently clamping or producing broken ffmpeg output, a clip too short
   for the fixed 0.5s crossfade **halts the render** with a clear per-clip message, the same
   halt-and-report philosophy Phase 1 already established for Layer 3 (never guess, never
   silently produce corrupt output). With only 1 clip, crossfade is a no-op (nothing to
   transition between) and Clip Story falls back to the existing hard-cut path
   automatically — mirrors Slideshow's `len(image_paths) > 1` guard.
6. **Music provider default and GUI ordering mirror Slideshow's actual (not imagined)
   behavior** — static `"jamendo"` default, Jamendo listed first in the dropdown, no new
   "check key cache" branch invented (see investigation above).
7. **Local-folder music provider and `resolve_music_track()` are Clip-Story-owned copies**
   (new `clipstory_music.py`), not shared with Slideshow's — consistent with the
   already-made shared-core decision not to unify "local" music across features.
8. **Stage tracker stays a single `"ClipStory Assembly"` stage for Phase 2**, not split
   into per-feature stages (captions/music/transition are all sub-steps inside the same
   per-clip-then-concat-then-mux flow, not separate long-running phases the way
   TTS/Assembly/Mux are for Slideshow) — avoids GUI-side stage-tracker changes not
   requested by the task.
9. **Opportunistic cleanup taken: (a) and (b) from the investigation findings above**
   (both inside `clipstory_ffmpeg.py`, which this phase edits directly for crossfade/
   captions/music anyway). **Not taken:** the narration-textarea `innerHTML` GUI item
   (different region of `app.js`) and the Back-navigation Start-button state leak (no
   contact with this phase's files) — both explicitly reported as still-deferred in the
   final report, per the task's own instruction not to go looking for cleanup outside the
   touched neighborhood.

## Package structure

```
docu_studio/clipstory/
    clipstory_config.py      # + fields on ClipStoryConfig: transition: str = "cut"
                              # ("cut"|"crossfade"), captions: bool = False,
                              # music_enabled: bool = False, music_provider: str =
                              # "jamendo" ("jamendo"|"local_folder"), music_folder: str
                              # = "". All default to Phase 1's exact prior behavior.
    clipstory_music.py       # NEW. LocalFolderMusicProvider + resolve_music_track(),
                              # copied from slideshow_music.py's shape, reusing
                              # common.music_jamendo.JamendoMusicProvider/TrackCandidate
                              # unchanged. Own cache-dir-adjacent constants only where
                              # Jamendo's shared cache doesn't already cover it (it
                              # does — common/music_jamendo.py's cache dir is already
                              # unified across features, nothing new needed there).
    clipstory_ffmpeg.py       # + methods on ClipStoryFFmpeg:
                              #   burn_captions(video_path, ass_path, output_path)
                              #     — copies SlideshowFFmpeg.burn_captions verbatim
                              #     (cwd-relative subtitles= workaround, finalize_filter).
                              #   mix_music_bed(voice_path, music_path, duration,
                              #     output_path) — copies SlideshowFFmpeg.mix_music_bed
                              #     verbatim, deferred import of
                              #     common.audio_ducking.build_ducking_filtergraph,
                              #     .m4a output (not .mp3 — aac codec/container match,
                              #     same gotcha Slideshow already hit and documented).
                              #   concat_segments_with_xfade(segment_paths, durations,
                              #     transition_duration, output_path) — NEW technique,
                              #     chains xfade(video)+acrossfade(audio) pairwise
                              #     across already-AV-muxed segments in one
                              #     filter_complex (see Data flow below for the exact
                              #     filter chain), finalize_filter on the final video
                              #     stage only.
                              #   concat_segments(...) — unchanged behavior, redundant
                              #     per-segment `scale=` in its filter_complex replaced
                              #     with `fps=30` only (cleanup item (b) — segments are
                              #     already exactly output_resolution from
                              #     normalize_clip, re-scaling was always a no-op
                              #     re-encode).
                              #   apply_reconciliation(...)'s "none" branch — shutil.copy
                              #     wrapped in try/except OSError, raising FFmpegError
                              #     on failure (cleanup item (a), consistent with every
                              #     other method in this class).
    clipstory_assembly.py    # + pipeline steps: per-clip caption burn (deferred import
                              # of common.captions, between normalize_clip and
                              # mux_audio_video), crossfade-vs-hard-cut concat branch,
                              # final music mix (deferred import via
                              # clipstory_ffmpeg.mix_music_bed) before the final output
                              # is returned. New function parameters all default to
                              # Phase 1 behavior — a caller passing none of them gets
                              # byte-identical output to today.
    clipstory_runner.py      # + resolves music track (via clipstory_music.resolve_
                              # music_track) before calling assemble_clip_story, exactly
                              # mirroring SlideshowRunner's ordering — music resolution
                              # happens once, outside the per-clip loop, and the
                              # resolved local path is threaded through as a parameter.
```

No new module is needed for captions or ducking — both are 100% direct calls into
`common/captions.py` / `common/audio_ducking.py`, deferred-imported inside
`clipstory_assembly.py` / `clipstory_ffmpeg.py` exactly as Slideshow does it.

## Data flow

**Per-clip loop** (unchanged steps from Phase 1 are not re-described; only insertions are
detailed):

1. `trim_clip` → `measured_target_duration = get_duration(trimmed)` (unchanged).
2. `normalize_clip` → `normalized_path` (unchanged; video-only, already
   `finalize_filter`'d).
3. **NEW, only if `config.captions`:** after TTS/Layer-2/Layer-3/reconciliation have
   produced `final_narration_path` for this clip (so the clip's *actual* final narration
   duration is known — it equals `measured_target_duration` by construction, since
   reconciliation lands it there):
   `timings = estimate_word_timestamps(clip.script_text, measured_target_duration)` →
   `write_ass_file(timings, ass_path, out_w, out_h, measured_target_duration)` →
   `ffmpeg.burn_captions(normalized_path, ass_path, captioned_path)`. The video path used
   for this clip's mux step becomes `captioned_path` instead of `normalized_path`. If
   `config.captions` is False, this step is skipped entirely — `normalized_path` flows
   through unchanged, byte-identical to Phase 1.
4. TTS → Layer 2/3 fit → reconciliation → `final_narration_path` (unchanged from Phase 1).
5. `mux_audio_video(video_path, final_narration_path, segment_path)` where `video_path` is
   whichever of `normalized_path`/`captioned_path` applies (unchanged call, just a
   conditional input).

**After the per-clip loop:**

6. **Concat branch**, keyed on `config.transition`:
   - `"cut"` (default): `ffmpeg.concat_segments(segment_paths, output_resolution,
     assembled_path)` — same call as Phase 1, minus the redundant-scale cleanup.
   - `"crossfade"`: validate first — `len(segment_paths) >= 2` (else silently fall back to
     `"cut"`, matching Slideshow's `len(image_paths) > 1` guard — a single clip has nothing
     to transition between) and every clip's measured duration `> transition_duration`
     (else halt with a clear message naming the offending clip, per decision 5). Then
     `ffmpeg.concat_segments_with_xfade(segment_paths, durations, 0.5, assembled_path)`.
     Filter chain per pair `i, i+1` (mirroring Slideshow's cumulative-offset technique,
     video side, plus a parallel audio chain with no offset needed since `acrossfade`
     self-aligns on stream tails/heads):
     ```
     [0:v][1:v]xfade=transition=fade:duration=0.5:offset=<cum0-0.5>[x1v];
     [0:a][1:a]acrossfade=d=0.5[x1a];
     [x1v][2:v]xfade=transition=fade:duration=0.5:offset=<cum1-0.5>[x2v];
     [x1a][2:a]acrossfade=d=0.5[x2a];
     ... -> [vout] (finalize_filter'd) / [aout]
     ```
     mapped to `-map [vout] -map [aout]`. Offsets computed from each segment's own
     `measured_target_duration` via the same cumulative-minus-overlap math as Slideshow's
     `_xfade_offsets` (reused verbatim as a static method, parameterized on durations —
     no Slideshow import, a Clip-Story-local copy of the same technique).
7. **NEW, only if `config.music_enabled`:** music track already resolved once at the
   `clipstory_runner.py` level (before `assemble_clip_story` runs), passed in as
   `music_path: str | None`. If a track was resolved:
   `total_duration = ffmpeg.get_duration(assembled_path)` →
   `ffmpeg.mix_music_bed(assembled_path, music_path, total_duration, mixed_audio_path)`
   (passing the assembled AV file directly as the "voice" input — ffmpeg's `[0:a]`
   reference in `build_ducking_filtergraph`'s output resolves to the assembled file's own
   narration audio stream automatically, no separate audio-extraction pass needed) →
   `ffmpeg.mux_audio_video(assembled_path, mixed_audio_path, output_path)` (re-muxes the
   assembled video against the new music-mixed audio, discarding the assembled file's
   original narration-only audio track, via the existing `-map 0:v:0 -map 1:a:0`
   discipline — no changes to `mux_audio_video` itself). If `resolve_music_track` returned
   `None` (no usable track from either provider) or `config.music_enabled` is False,
   `assembled_path` is copied/renamed straight to `output_path` — final behavior identical
   to Phase 1's direct `concat_segments(...) → output_path` in that case.

**Runner-level (`clipstory_runner.py`), before calling `assemble_clip_story`:**

- If `config.music_enabled`: `resolve_music_track(config.music_provider, mood="cinematic",
  max_duration=<sum of all clip durations, rough upper bound>, jamendo_client_id=...,
  local_folder=config.music_folder)` → `(local_path, label) | None`, passed through as a
  parameter. Mirrors `SlideshowRunner`'s ordering (resolve music before assembly starts,
  thread the path through as data, no interleaving of network/IO with the render loop).

## GUI

New controls added to the existing Clip Story mode-card block in `index.html`, directly
below the existing `clipstory-canvas-row`, same Tailwind styling and same
show/hide-by-mode pattern already used for every mode-specific row:

- Transition `<select id="clipstory-transition-select">`: Hard cut / Crossfade — same two
  options, same order, as `slideshow-transition-select`.
- Captions checkbox `id="clipstory-captions-toggle"`.
- Music checkbox `id="clipstory-music-toggle"` (`onchange="onClipStoryMusicToggleChange()"`)
  + provider `<select id="clipstory-music-provider-select">` (Jamendo first, Local folder
  second — matches investigation finding on static ordering) + folder row
  `id="clipstory-music-folder-row"`/`id="clipstory-music-folder"` (shown only when Local
  folder selected) + Browse button (`browseClipStoryMusicFolder()`, calls
  `window.pywebview.api.browse_folder()` — reuses the same bridge method Slideshow's
  folder browse already uses).

`app.js` additions, mirroring the Slideshow equivalents 1:1:

- `onClipStoryMusicToggleChange()` / `onClipStoryMusicProviderChange(provider)` — show/hide
  provider row / folder row.
- `browseClipStoryMusicFolder()`.
- `startRun()`'s existing `clipstory` branch (currently sends `topic`,
  `output_resolution`, per-clip fields) gains `transition`, `captions`, `music_enabled`,
  `music_provider`, `music_folder` keys, read off the new DOM elements the same way
  Slideshow's branch reads its equivalents.

`gui/bridge.py`: `start_clipstory_run(config: dict)` gains the same
`config.get("transition", "cut")` / `config.get("captions", False)` /
`config.get("music_enabled", False)` / `config.get("music_provider", "jamendo")` /
`config.get("music_folder", "")` reads `start_slideshow_run` already has, resolves
`jamendo_client_id = key_cache.get("docu_studio_jamendo") or ""` the same way, and passes
all of it into `ClipStoryConfig`.

Cache-bust: `webview_app.py`'s `?v=13` → `?v=14`.

A user who touches none of the new controls gets Phase 1's exact prior output — verified
explicitly in the all-off E2E run (see Verification).

## Error handling

- **Crossfade with a too-short clip** → halt before any ffmpeg crossfade call runs, with a
  message naming the specific clip(s) and their measured duration vs. the fixed 0.5s
  transition requirement — same halt-and-report philosophy as Phase 1's Layer 3, surfaced
  through the existing `ErrorEvent`/`ClipStoryFitError`-style path (a new, similarly-named
  exception, not a reuse of `ClipStoryFitError` itself since this isn't a pacing-fit
  failure).
- **Crossfade with exactly 1 clip** → silent fallback to hard-cut concat (no error, nothing
  to transition between) — matches Slideshow's precedent exactly.
- **Music resolution failure (no usable track from either provider)** → logged, music bed
  skipped, render continues and produces the same output as `music_enabled = False` would
  — never raises, matches `resolve_music_track`'s existing no-raise contract.
- **Captions/music/transition ffmpeg failures otherwise** propagate as `FFmpegError`
  through the existing runner error-surface pattern — no new error-handling pattern
  invented.
- **`apply_reconciliation`'s "none" branch** (cleanup item) now raises `FFmpegError` (not a
  raw `OSError`) on a `shutil.copy` failure, consistent with every other method.

## Testing

Unit tests per new/changed module, same rigor as Phase 1's and Slideshow Phase 3's:

- `clipstory_ffmpeg.py`:
  - `burn_captions` — golden filter-string assertion (`subtitles=<name>`, wrapped in
    `finalize_filter`), subprocess mocked.
  - `mix_music_bed` — asserts `build_ducking_filtergraph` output is passed through, `.m4a`
    output path convention, `-map [aout]` present, subprocess mocked.
  - `concat_segments_with_xfade` — golden filter_complex string assertions across 2 and 3+
    segments: correct pairwise `xfade`/`acrossfade` chaining, correct cumulative
    `offset=` values (table-driven against known durations), `finalize_filter` applied only
    to the final video stage, `-map [vout] -map [aout]` present. Raises on `< 2` segments.
  - `concat_segments` — updated golden filter-string assertion reflecting the
    `fps=30`-only (no redundant `scale=`) cleanup.
  - `apply_reconciliation`'s `"none"` branch — mocked `shutil.copy` raising `OSError` →
    asserts `FFmpegError` is raised (new test case; existing pad/trim_fade branch tests
    unchanged).
- `clipstory_music.py` — `LocalFolderMusicProvider` (empty/missing folder → `[]`, populated
  folder → deterministic pick via seeded `random.Random`, same test shape as
  `test_slideshow_music.py`), `resolve_music_track`'s fallback chain (Jamendo candidates →
  used; Jamendo empty → local folder; both empty → `None`), all HTTP/filesystem mocked, no
  network.
- `clipstory_assembly.py` — orchestration test extended with cases for: captions enabled
  (asserts `estimate_word_timestamps`/`write_ass_file`/`burn_captions` called with
  clip-local text and clip-local duration, per clip, not a global/whole-project call),
  crossfade enabled with valid durations (asserts `concat_segments_with_xfade` called
  instead of `concat_segments`), crossfade with a too-short clip (asserts the halt fires
  before any concat call), crossfade with exactly 1 clip (asserts fallback to
  `concat_segments`), music enabled with a resolved track (asserts `mix_music_bed` +
  re-mux sequence), music enabled with no resolved track (asserts output identical to
  music-disabled path). All-off case re-asserts Phase 1's exact existing call sequence
  (regression guard).
- `clipstory_config.py` — new field defaults, `transition` value validation
  (`"cut"`/`"crossfade"` only, same pattern as `output_resolution`'s validation).
- Baseline: reconfirmed fresh at phase start (see Standing constraints) — report the new
  pass/fail count at completion, called out against this baseline.

## Real end-to-end verification (required before sign-off)

- **All-on run**: captions + music + crossfade together, through the real pipeline (real
  narration from Phase 1's TTS/Layer-2/Layer-3/reconciliation flow, real ffmpeg, 3+
  uploaded clips of varying duration so at least one crossfade transition and one caption
  burn per clip actually execute). Extract and personally inspect:
  - Caption sync per segment — captions appear only within their own clip's span, no
    caption bleeding across a cut into the next clip's narration.
  - Crossfade blend quality at cut points — visually smooth blend, no visible SAR
    artifacts, no audio pop/glitch/desync at the transition (confirms the xfade+acrossfade
    sync-by-construction design actually holds under real encoding, not just in the
    filter-string math).
  - No regressions from `normalize_clip` interacting with the new crossfade path — every
    segment individually finalized before crossfade, exactly as Phase 1 already guarantees.
- **All-off run**: confirms Phase 1 behavior is byte-for-byte/structurally unchanged
  (hard cut, no captions, no music) — same clips, compare output structurally (duration,
  segment boundaries) against a Phase-1-equivalent run.
- Report back explicitly what's verified-by-eyes vs. verified-by-logs-only, same standard
  as every prior phase's delivery checkpoint.

## Delivery checkpoint

After Phase 2 code is written and unit tests pass: kill and restart the app, run the
all-on and all-off real E2E scenarios above, and report pass/fail counts plus the
verified-by-eyes findings before considering Clip Story feature-complete relative to
Slideshow's polish level.
