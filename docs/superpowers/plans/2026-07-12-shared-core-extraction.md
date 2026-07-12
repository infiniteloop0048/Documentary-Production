# Shared-Core Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan family-by-family. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract five shared modules under `docu_studio/common/` for the six
duplicated technique families confirmed in the inventory, repoint Shorts and
Slideshow at them one family at a time, verify each side independently, then
delete the old duplicated file. Zero user-visible behavior change in either
feature, except the intentional Jamendo-cache-dir merge (family: music).

**Inventory:** `docs/superpowers/specs/2026-07-12-shared-core-inventory.md`
**Design spec:** `docs/superpowers/specs/2026-07-12-shared-core-design.md`

Read both before starting any task below — this plan assumes their findings
and does not re-derive them.

## Global constraints

- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files),
  `history/`, `licensing.py`. Existing test files may only have their
  **import lines** repointed — no assertion/logic changes — per the explicit
  test-file-handling decision above (this is the one exception to "don't
  touch existing test files unless fixing a bug," scoped narrowly to imports).
- Correct venv is `.venv/`, never `venv/`. Restart before any live/E2E check:
  `pkill -f docu_studio 2>/dev/null; DISPLAY=:1 .venv/bin/python -m docu_studio`
- Baseline confirmed at worktree setup: **589 passed / 24 failed / 1
  collection error** (`tests/integration/test_edge_tts_adapter.py`,
  pre-existing, unrelated). Every task's test run must not change this
  baseline except by adding new passing tests for `common/` modules and by
  net-decreasing the file count as old duplicated files are deleted.
- One family per task group below. Commit after each of the five steps
  (extract, repoint-Shorts+verify, repoint-Slideshow+verify, delete-old) —
  or combine repoint+verify into one commit per side if the diff is small,
  but never combine two families into one commit.
- **E2E means a real run through the GUI or a scripted pipeline invocation
  that produces actual output video/audio, with the output inspected — not
  just "tests pass."** For each family, do this on both Shorts and
  Slideshow, not just one, per the task's own instructions.
- Do not push without explicit go-ahead.

---

## Task Group A: `common/audio_ducking.py` (family 3 — start here, lowest risk)

Verbatim move, zero signature changes, zero behavior fork. Good first family
to prove the extract→repoint→verify→delete rhythm.

- [ ] **A1. Extract.** Create `docu_studio/common/__init__.py` (empty) and
  `docu_studio/common/audio_ducking.py` containing `_FADE_SECONDS`,
  `_MUSIC_BASELINE_DB`, `build_ducking_filtergraph()` — copied verbatim from
  either `shorts_audio_mix.py` or `slideshow_audio_mix.py` (they're
  byte-identical; diff them first to confirm before copying, per the
  inventory's claim). Write `tests/unit/test_common_audio_ducking.py`
  covering the same cases as the two existing test files combined (dedupe
  identical cases, keep the union of edge cases if they differ at all).
  Run: `.venv/bin/python -m pytest tests/unit/test_common_audio_ducking.py -v`

- [ ] **A2. Repoint Shorts.** In `docu_studio/shorts/shorts_ffmpeg.py`,
  change the import inside `mix_music_bed()` from
  `docu_studio.shorts.shorts_audio_mix` to `docu_studio.common.audio_ducking`.
  Repoint `tests/unit/test_shorts_audio_mix.py`'s import to
  `docu_studio.common.audio_ducking` (or delete it if A1's new test already
  covers every case it did — prefer deleting duplication over keeping two
  test files exercising the same function, but confirm no Shorts-specific
  case exists first).
  Run: `.venv/bin/python -m pytest tests/unit/ -k "shorts and audio" -v`
  Run full Shorts suite: `.venv/bin/python -m pytest tests/unit/ -k shorts -v`
  **E2E:** restart app, run one real Shorts generation with music enabled,
  inspect the output video's audio track (ducking audible, narration
  dominant) — not just that the file exists.

- [ ] **A3. Repoint Slideshow.** Same pattern in
  `docu_studio/slideshow/slideshow_ffmpeg.py`'s `mix_music_bed()`, and
  `tests/unit/test_slideshow_audio_mix.py`.
  Run: `.venv/bin/python -m pytest tests/unit/ -k "slideshow and audio" -v`
  Run full Slideshow suite: `.venv/bin/python -m pytest tests/unit/ -k slideshow -v`
  **E2E:** restart app, run one real Slideshow generation with music enabled,
  inspect the output the same way.

- [ ] **A4. Delete old files.** `docu_studio/shorts/shorts_audio_mix.py`,
  `docu_studio/slideshow/slideshow_audio_mix.py` — confirm nothing else
  imports them (`grep -rn "shorts_audio_mix\|slideshow_audio_mix" docu_studio/ tests/`)
  before deleting. Full test suite run, confirm baseline unchanged except for
  the net file/test delta.

- [ ] **A5. Commit.** One commit for this family (or A1 separately from
  A2-A4 if the diff is large — judgment call, but don't split further).

---

## Task Group B: `common/ffmpeg_finalize.py` (family 5 — second, also low risk)

- [ ] **B1. Extract.** Create `docu_studio/common/ffmpeg_finalize.py` with
  `_SAR_PIXFMT_SUFFIX = "setsar=1,format=yuv420p"` and
  `finalize_filter(filter_chain: str) -> str` as a **module-level function**
  (not a class method — neither existing implementation uses `self`). Check
  first whether any test asserts on the literal suffix string or calls
  `_finalize_filter` directly (design spec flagged this as unverified) —
  `grep -rn "finalize_filter\|SAR_PIXFMT" tests/`. Write a small
  `tests/unit/test_common_ffmpeg_finalize.py` if none of the existing tests
  cover it directly (likely — it's probably only exercised indirectly
  through other ffmpeg method tests).

- [ ] **B2. Repoint Shorts.** In `shorts_ffmpeg.py`: delete the local
  `_SAR_PIXFMT_SUFFIX` constant and `_finalize_filter` staticmethod; import
  `finalize_filter` from `docu_studio.common.ffmpeg_finalize`; update all
  four call sites (`self._finalize_filter(...)` → `finalize_filter(...)`) at
  the lines the inventory named (vertical_convert, apply_ken_burns,
  apply_speed_ramp, generate_punch_card — confirm exact line numbers at
  migration time, they may have shifted).
  Run: `.venv/bin/python -m pytest tests/unit/ -k shorts -v`
  **E2E:** restart app, run one real Shorts generation exercising Ken Burns
  + a punch card if the feature toggle allows it in one run; inspect the
  output plays cleanly (no concat failures from SAR mismatch — the exact
  failure mode this suffix prevents).

- [ ] **B3. Repoint Slideshow.** Same pattern in `slideshow_ffmpeg.py` — note
  one call site (`concat_segments_with_xfade`, xfade's last stage) uses the
  raw `_SAR_PIXFMT_SUFFIX` constant inline rather than the helper function;
  import the constant too if that call site needs it, or route it through
  `finalize_filter` if the surrounding code structure allows — check which
  is the smaller diff at migration time.
  Run: `.venv/bin/python -m pytest tests/unit/ -k slideshow -v`
  **E2E:** restart app, run one real Slideshow generation with crossfade
  transitions enabled (the xfade call site is the one most likely to be
  affected by any mistake here); inspect output plays cleanly.

- [ ] **B4. Delete old code.** Remove the now-empty local definitions in both
  ffmpeg files (the files themselves stay — they have other content). Full
  suite run, confirm baseline.

- [ ] **B5. Commit.**

---

## Task Group C: `common/resilient_download.py` (family 1)

- [ ] **C1. Extract.** Create `docu_studio/common/resilient_download.py`
  with `BROWSER_USER_AGENT`, all six tuning constants, `build_download_session()`,
  `_is_retriable()`, and `download_resilient()` (renamed from
  `download_clip_resilient`/`download_photo_resilient` per the design spec —
  confirm the new name doesn't collide with anything already imported
  wildcard-style in either assembly file). Write
  `tests/unit/test_common_resilient_download.py` covering retry/backoff/
  pacing/chunked-write behavior — likely a near-direct port of
  `test_shorts_footage_download.py`'s cases since that's the more complete
  of the two existing test files per the inventory.

- [ ] **C2. Repoint Shorts.** `shorts_assembly.py`: import
  `build_download_session`, `download_resilient` from
  `docu_studio.common.resilient_download` instead of
  `docu_studio.shorts.shorts_footage_download`; update the call site in
  `_collect_clips_per_sentence` (rename `download_clip_resilient` call to
  `download_resilient`). Do **not** touch `_collect_clips`'s separate
  non-resilient `download_clip` path — out of scope, confirmed pre-existing.
  Repoint `test_shorts_footage_download.py`'s imports.
  Run: `.venv/bin/python -m pytest tests/unit/ -k shorts -v`
  **E2E:** restart app, run one real Shorts generation that exercises footage
  download from a live provider (not mocked) — confirm clips download and
  assemble correctly, watch logs for any retry/backoff messages behaving as
  expected under normal conditions.

- [ ] **C3. Repoint Slideshow.** `slideshow_photo_download.py` keeps
  `fetch_topic_images`/`_dedup_key`/`_MAX_POOL_MULTIPLIER` in place, but its
  `build_download_session`/`_is_retriable`/`download_photo_resilient`
  definitions are deleted and replaced with an import from `common/`
  (rename the call to `download_resilient`). Repoint
  `test_slideshow_photo_download.py` (or wherever its coverage lives —
  confirm exact test filename at migration time) imports.
  Run: `.venv/bin/python -m pytest tests/unit/ -k slideshow -v`
  **E2E:** this download path is only reachable via the GUI's
  "fetch topic images" preview flow (`Bridge.fetch_slideshow_images`), not
  the main assembly pipeline — per the inventory. Restart app, trigger that
  specific GUI flow with a live provider, confirm images download and the
  preview populates correctly. This is a different E2E surface than the
  main Slideshow render — don't substitute a full slideshow render for it,
  it wouldn't touch this code path at all.

- [ ] **C4. Delete old files.** `docu_studio/shorts/shorts_footage_download.py`
  is fully deleted (nothing else in it). Confirm no other imports first.

- [ ] **C5. Commit.**

---

## Task Group D: `common/music_jamendo.py` (family 2)

Highest-risk family alongside captions — includes the intentional cache-dir
merge. Do this after C (download) since it reuses `download`-adjacent
patterns, but before D depends on nothing from C directly.

- [ ] **D1. Extract.** Create `docu_studio/common/music_jamendo.py` with
  `JAMENDO_API_URL`, `DEFAULT_MUSIC_MOOD`, `_REQUEST_TIMEOUT`,
  `_MAX_TRACK_DURATION`, `_MUSIC_CACHE_DIRNAME = "music_cache"` (new unified
  name — **not** `"shorts_music_cache"` or `"slideshow_music_cache"`),
  `music_cache_dir()`, `safe_cache_filename()`, `TrackCandidate` (shared
  dataclass with `bpm: int | None = None`, `source: str` required — no class
  default per design spec), `JamendoMusicProvider`. Write
  `tests/unit/test_common_music_jamendo.py` covering search/fetch/cache-hit/
  cache-miss/empty-client-id/malformed-response cases — union of the
  Jamendo-related cases in both existing test files.

- [ ] **D2. Repoint Shorts.** `music_providers.py`: delete local
  `JamendoMusicProvider`, `music_cache_dir`, `safe_cache_filename`,
  `JAMENDO_API_URL`, `DEFAULT_MUSIC_MOOD`, `_REQUEST_TIMEOUT`,
  `_MAX_TRACK_DURATION`, `TrackCandidate`; import all from `common/`.
  `LocalMusicProvider` and `resolve_music_track()` stay, now referencing the
  imported `TrackCandidate`/`JamendoMusicProvider`. Repoint
  `test_shorts_music_providers.py` imports — **and update any assertion
  checking the cache-dir path** from `"shorts_music_cache"` to
  `"music_cache"` (a real assertion change, not a mechanical import fix —
  don't skip this expecting the old string to still be right).
  Run: `.venv/bin/python -m pytest tests/unit/ -k shorts -v`
  **E2E:** restart app, run one real Shorts generation with
  `music_provider="jamendo"` and a live `client_id`, confirm a track
  downloads into `<config_dir>/music_cache/` (not the old dirname — verify
  the path directly, don't just trust the run succeeded), confirm bpm still
  flows into beat-sync (check logs for `resolve_beat_grid` tier used).

- [ ] **D3. Repoint Slideshow.** Same pattern in `slideshow_music.py`:
  `LocalFolderMusicProvider` and `resolve_music_track()` stay, Jamendo/cache
  pieces come from `common/`. Repoint `test_slideshow_music.py` imports and
  cache-dir assertion (`"slideshow_music_cache"` → `"music_cache"`).
  Run: `.venv/bin/python -m pytest tests/unit/ -k slideshow -v`
  **E2E:** restart app, run one real Slideshow generation with
  `music_provider="jamendo"`, confirm track downloads into the same unified
  `music_cache/` dir. If a Shorts run in D2 already cached a track with the
  same title, this is the moment to confirm the cross-feature cache-hit
  actually works as designed (a positive confirmation of the intended
  behavior change, not just an absence-of-regression check).

- [ ] **D4. Delete old code.** Remove now-empty local definitions from
  `music_providers.py`/`slideshow_music.py` (files stay, they still house
  `LocalMusicProvider`/`LocalFolderMusicProvider`/`resolve_music_track`).
  Note in the commit message that `<config_dir>/shorts_music_cache/` and
  `<config_dir>/slideshow_music_cache/` are now orphaned on any machine that
  ran the old code — intentionally left in place, not cleaned up.

- [ ] **D5. Commit.**

---

## Task Group E: `common/captions.py` (family 4 — do last, highest complexity)

The only family requiring a real code addition (punch_window ported into
Slideshow's parameterized signature), not just a lift. Do this after the
other four are proven out.

- [ ] **E1. Extract.** Create `docu_studio/common/captions.py` with:
  `WordTiming` (single canonical dataclass), `estimate_word_timestamps()`
  (Tier-3, verbatim), `group_words`, `_escape_ass_text`, `_format_ass_time`,
  `_render_group_text`, `_ASS_HEADER_TEMPLATE`, `_MIN_GROUP`, `_MAX_GROUP`,
  `_MIN_WORD_DURATION`, `_FONT_NAME`, `_SAFE_AREA_BOTTOM_FRACTION = 0.22`
  (Slideshow's fraction-based version, not Shorts' baked-pixel constant).
  Write `generate_ass(timings, out_width, out_height, audio_duration=None, punch_window=None)`
  and `write_ass_file(timings, output_path, out_width, out_height, audio_duration=None, punch_window=None)`
  starting from Slideshow's version (already width/height-parameterized) and
  porting in Shorts' punch_window split/clamp/drop logic (~20 lines,
  currently in `shorts_captions.py::generate_ass` between the group-flattening
  loop and the Dialogue-line emission) **unchanged** — this is the one place
  in the whole extraction where behavior-preserving code literally moves
  from one signature shape into another, so review this diff line-by-line
  against the original before considering it done, not just "tests pass."
  Write `tests/unit/test_common_captions.py` covering: the union of both
  existing test files' cases, PLUS an explicit case exercising punch_window
  with a non-default out_width/out_height (a combination neither existing
  test file covers, since Shorts never varies dimensions and Slideshow never
  uses punch_window — this is the one genuinely new test scenario the merge
  requires).

- [ ] **E2. Repoint Shorts.** `capability_resolvers.py`: delete local
  `WordTiming` and `estimate_word_timestamps`, import both from
  `docu_studio.common.captions`. Tier-resolution logic
  (`_tier1_native_timestamps`, `_tier2_whisper_alignment`,
  `get_word_timestamps`, `resolve_beat_grid`) untouched. `shorts_assembly.py`:
  update the `write_ass_file` call to pass `SHORTS_WIDTH, SHORTS_HEIGHT`
  explicitly (import from `shorts_config.py` — confirm it's not already
  imported under a different alias at that call site) alongside the existing
  `audio_duration`/`punch_window` kwargs. Repoint
  `test_shorts_captions.py` imports (`WordTiming` from
  `docu_studio.common.captions` now, not `capability_resolvers`).
  Run: `.venv/bin/python -m pytest tests/unit/ -k shorts -v`
  **E2E:** restart app, run one real Shorts generation with captions AND
  punch-card both enabled in the same run (the combination that exercises
  the ported split/clamp logic) — inspect the burned-in captions visually
  in the output video: correct dimensions (1080x1920 positioning), no
  caption overlapping the punch card, no caption gap/flicker at the punch
  card boundary.

- [ ] **E3. Repoint Slideshow.** `slideshow_assembly.py`: change the import
  from `docu_studio.slideshow.slideshow_captions` to
  `docu_studio.common.captions` for both `estimate_word_timestamps` and
  `write_ass_file` — call site itself (`write_ass_file(timings, ass_path, out_width, out_height, audio_duration)`)
  needs no argument changes, `punch_window` defaults to `None`. Repoint
  `test_slideshow_captions.py` imports.
  Run: `.venv/bin/python -m pytest tests/unit/ -k slideshow -v`
  **E2E:** restart app, run one real Slideshow generation with captions
  enabled at a non-default aspect ratio (16:9 or 1:1, not 9:16) — inspect
  the burned-in captions visually: correctly positioned/sized for that
  aspect ratio, confirming the shared function's width/height parameterization
  still works now that it also carries the punch_window branch (make sure
  the added logic didn't regress the no-punch_window default path).

- [ ] **E4. Delete old files.** `shorts_captions.py`, `slideshow_captions.py`
  fully deleted. Confirm no other imports first
  (`grep -rn "shorts_captions\|slideshow_captions" docu_studio/ tests/`).

- [ ] **E5. Commit.**

---

## Final steps (after all five task groups)

- [ ] Full test suite run: `.venv/bin/python -m pytest tests/ --ignore=tests/integration/test_edge_tts_adapter.py -v`
  — confirm 589+N passed (N = new `common/` tests added) / 24 failed
  (unchanged pre-existing failures) / same 1 collection error.
- [ ] `grep -rn "shorts_footage_download\|slideshow_photo_download.*build_download_session\|shorts_audio_mix\|slideshow_audio_mix\|shorts_captions\|slideshow_captions" docu_studio/` —
  confirm zero stray references to deleted symbols anywhere.
- [ ] Write the final handoff report (separate task, not part of this plan's
  checkboxes — see task list).
