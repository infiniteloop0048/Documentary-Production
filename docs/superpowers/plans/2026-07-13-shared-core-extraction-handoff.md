# Shared-Core Extraction — Final Handoff Report

Branch: `shared-core-extraction`, worktree: `.worktrees/shared-core-extraction/`
9 commits on top of `938d8bd` (main): 4 docs commits (inventory, design spec,
migration plan, a heading-rename fix) + 5 code commits, one per family.

---

## 1. What was extracted

Five modules under `docu_studio/common/`, replacing six duplicated technique
families (one pair — the Tier-3 word-timestamp estimator — folded into the
captions module rather than getting its own file, since it had no separate
consumer):

| `common/` module | Families covered | Commit |
|---|---|---|
| `audio_ducking.py` | Sidechain-ducking filtergraph construction | `bbf6ec5` |
| `ffmpeg_finalize.py` | `setsar=1,format=yuv420p` segment-finalize suffix | `154a345` |
| `resilient_download.py` | Retry/backoff/pacing HTTP download primitives | `6e1996e` |
| `music_jamendo.py` | Jamendo API client + track cache | `6dc8060` |
| `captions.py` | ASS caption generation + Tier-3 word-timestamp estimator | `1926e25` |

**Two families from the original inventory were confirmed NOT duplicated**
during Step 1 (see `docs/superpowers/specs/2026-07-12-shared-core-inventory.md`)
and correctly excluded from extraction:
- Crossfade/xfade transition logic — Slideshow-only, Shorts has no transitions.
- Word-timing tier-resolution system + TTS pace calibration — Shorts-only;
  Slideshow has no Whisper alignment tier and no persisted WPM calibration.

## 2. What stayed feature-specific (by design, not oversight)

- **Music local-source providers**: `LocalMusicProvider` (Shorts, manifest-driven)
  and `LocalFolderMusicProvider` (Slideshow, folder-scan) — genuinely different
  data models, not duplicates.
- **The two `resolve_music_track()` functions**: deliberately NOT unified.
  Shorts' returns a 3-tuple `(path, label, bpm)` feeding beat-sync; Slideshow's
  returns a 2-tuple `(path, label)` — Slideshow has no beat-sync concept. Both
  now call into the shared `JamendoMusicProvider`/`TrackCandidate`/cache helpers.
- **Shorts' 3-tier word-timing resolution system** (`capability_resolvers.py`:
  native-TTS tier, Whisper-alignment tier, tier-selection logic) — untouched,
  Shorts-only, no Slideshow equivalent exists to share it with.
- **Slideshow's crossfade/xfade transition logic** — untouched, Shorts-only
  gap in the other direction (no transitions in Shorts to share with).
- **`fetch_topic_images()`/`_dedup_key()`** in `slideshow_photo_download.py` —
  Slideshow-specific orchestration on top of the shared download primitive.
- **`_collect_clips_per_sentence`/`_collect_clips`** in `shorts_assembly.py` —
  Shorts-specific orchestration (per-sentence pools, `{path,width,height}`
  dicts) on top of the same shared primitive.

## 3. Intentional behavior changes (not bugs — designed and verified)

**Jamendo cache-directory merge.** `_MUSIC_CACHE_DIRNAME` unified from two
separate per-feature dirs (`shorts_music_cache/`, `slideshow_music_cache/`)
to one shared `music_cache/` under the OS config dir. A Jamendo track
downloaded by either feature is now a cache hit for the other if the track
title matches (same key-derivation scheme, same stored format — confirmed
structurally compatible before merging). Old per-feature cache directories
are left in place, orphaned, not deleted or migrated — harmless, just unused
disk space until a user clears them manually.

No other behavior changes were made. Every other extraction preserved
call-site behavior exactly (confirmed by review + E2E below).

## 4. Verified by eyes vs. logs/tests only

**Verified by eyes (visual frame inspection or listening-equivalent audio
analysis), not just logs or automated assertions:**
- Audio ducking (Task 1): real ffmpeg mix of synthetic 800Hz/300Hz tones
  through both `ShortsFFmpeg.mix_music_bed()` and `SlideshowFFmpeg.mix_music_bed()`
  post-extraction, `volumedetect`-measured per-frequency-band loudness
  confirming voice (-29.1dB mean) meaningfully dominant over ducked music
  (-38.5dB mean, ~9.4dB gap) — identical measurements on both features.
- FFmpeg finalize (Task 2): `ffprobe` SAR inspection on real Shorts (Ken
  Burns + punch card) and real Slideshow (crossfade transition) output —
  SAR 1:1 confirmed on both, the exact property this suffix guarantees and
  the exact failure mode (`concat`/`xfade` rejecting mismatched SAR) it
  prevents.
- Resilient download (Task 3): real downloaded files inspected with `file`
  — 5 real JPEGs from live Pexels/Pixabay via `fetch_topic_images()`
  (Slideshow's only caller of this function, reachable only through the GUI
  photo-preview flow, not the main render pipeline), confirmed valid
  dimensions/EXIF, no corruption.
- Jamendo cache merge (Task 4): direct provider-level test — Shorts'
  `JamendoMusicProvider` downloaded a real track in 5.05s; Slideshow's
  separate `JamendoMusicProvider` instance fetched the identical candidate
  and got a cache hit in 0.00s at the same resolved path. Independently
  reconfirmed inside the live app: a full Slideshow run picked the same
  cached track by title and completed with real, audible, non-silent audio
  (`volumedetect` mean -20.5dB).
- Captions (Task 5, highest scrutiny): extracted video frames viewed
  directly —
  - Slideshow at 16:9 (a dimension Shorts never uses): caption correctly
    positioned in the lower-middle safe area at 1920×1080.
  - Shorts with captions + punch-card together: normal caption frame
    (correct text/position), punch-card frame (only punch-card text, zero
    caption overlap), and both boundary frames immediately before/after the
    punch window (12.7s / 12.9s) showing a clean transition with no glitch
    or double-render — direct visual confirmation of the ported
    split/clamp/drop logic working correctly in production.
  - The ported punch_window logic itself was verified three independent
    ways: the controller's own line-by-line read, the task reviewer's
    independent line-by-line trace of all five branches, and — most
    rigorously — git's own rename-diff mechanism: because the extraction
    was done as a file rename, the punch_window block never appears as a
    changed hunk in the diff, which is mechanical proof (not an assertion)
    that it is byte-identical unchanged context.

**Verified by logs/tests/decode-cleanliness only** (not frame-by-frame
visual inspection, since nothing in these families changes visible output):
- All five families' full real pipeline runs (both Shorts and Slideshow,
  multiple times per family) were confirmed via `ffmpeg -v error ... -f null -`
  (zero decode errors) and `ffprobe` stream inspection (correct codecs,
  durations, dimensions).

## 5. Test counts

- **Original baseline** (confirmed at worktree setup, before any change):
  589 passed / 24 failed / 1 collection error (unrelated, pre-existing —
  `tests/integration/test_edge_tts_adapter.py` imports a module that doesn't
  exist in this codebase, untouched by this work).
- **Final state** (after all 5 families): **570 passed / 24 failed / 1
  collection error** (same, unrelated).
- **Same 24 failure test IDs**, confirmed unchanged at every single task
  checkpoint throughout the refactor (theme/tokens dead-GUI-code attribute
  errors, a platform-layer ffprobe-path assumption, an unrelated settings
  default, an unrelated footage-assembly test, and integration tests needing
  live network/API access not available in CI) — zero new failures
  introduced by this work, zero pre-existing failures fixed or masked.
- **Net -19 passed** (589 → 570) is fully accounted for by test-file
  consolidation: at every task, duplicate test cases covering the newly-
  shared logic were deduped into one shared test file rather than kept as
  two near-identical copies, per an explicit user decision at the start of
  this work. No test coverage was lost — every task's report documents its
  dedup reasoning, and every dedup was independently verified by a task
  reviewer before being accepted.

## 6. Behavior deltas found and how resolved

Two deltas were found during the original inventory pass (Step 1) and
resolved by explicit design decisions before any code was written — not
discovered mid-migration:

1. **Captions: Shorts has `punch_window` support, Slideshow doesn't.**
   Resolved by porting the punch_window logic into the shared function
   (added as an optional parameter defaulting to `None`, which reproduces
   Slideshow's exact current behavior with zero code change needed at its
   call site).
2. **Captions: Shorts hardcodes 1080×1920, Slideshow is width/height-
   parameterized.** Resolved by adopting Slideshow's parameterized form as
   the shared shape (per the original task's explicit instruction — less
   duplication than the reverse), with Shorts now passing its own
   `SHORTS_WIDTH`/`SHORTS_HEIGHT` explicitly at its call site.

One additional delta was found and resolved during migration (Task 4):
3. **Music: `TrackCandidate.source` had different per-feature defaults**
   (`"local"` vs `"local_folder"`). Resolved by making `source` a required
   constructor argument on the shared dataclass (no default) — every
   existing call site, in both source files, already passed it explicitly.

No delta required a design compromise that changed either feature's
observable behavior beyond the one intentional cache-merge in §3.

## 7. Confirmation: both Shorts and Slideshow are unchanged from a user's perspective

Except for the Jamendo cache-dir merge (§3 — a strict improvement, not a
regression: fewer redundant downloads, invisible unless a user inspects
their config directory), every family's extraction was designed, reviewed,
and E2E-verified to produce **identical output** to before:

- Shorts: footage download, Ken Burns, punch cards, captions (including the
  punch-card interaction), music ducking, and Jamendo music resolution all
  behave exactly as before — verified via multiple real pipeline runs
  producing output with correct SAR, correct captions, correct audio
  levels, matching the pre-migration baseline runs.
- Slideshow: photo-preview fetching, crossfade transitions, captions at
  every supported aspect ratio, music ducking, and Jamendo music resolution
  all behave exactly as before — same verification method.

No GUI-visible behavior, no config default, no output file format or naming
changed. A user running either feature before and after this branch would
see no difference except (invisibly) fewer duplicate Jamendo downloads.

## 8. Process notes for future reference

- Every one of the five migration tasks went through: implementer (code +
  tests + commit only) → controller-run full-suite regression check →
  task-reviewer (spec compliance + code quality, dedicated subagent) →
  controller-run real E2E on both features. No task was marked complete
  without a clean review verdict and real E2E evidence.
- Two implementer dispatches were interrupted mid-run by transient
  infrastructure errors (a connection drop before Task 4's first attempt,
  and a backgrounding mistake during one of the E2E checks). Both were
  caught by checking `git status`/process state before treating any
  in-flight work as lost, and both were cleanly resumed or re-run without
  data loss.
- Jamendo's API was intermittently unreachable throughout this session
  (`ConnectionResetError`/`RemoteDisconnected`, unrelated to this
  refactor) — every family's E2E plan accounted for this by retrying and,
  where the app's own graceful-fallback behavior was the thing under test,
  treating a clean fallback-to-no-music as a valid (not degraded) result.
- No live Anthropic/OpenAI/OpenRouter/Groq key was available in this
  environment, so Shorts' full topic→LLM-script flow could not be run
  end-to-end as-is. Per an explicit user decision, E2E used a hand-written
  `ShortsScript` object fed directly into `assemble_short()` — every other
  stage (gTTS synthesis, real Pexels/Pixabay footage, real Jamendo music,
  real ffmpeg assembly) was genuine, live, unmocked pipeline code.

## 9. Ready for the video-upload feature

This extraction was explicitly the prerequisite for an upcoming video-upload
feature that will need several of these same techniques a third time. The
shared modules now available for it: `resilient_download.py` (download
primitives), `music_jamendo.py` (Jamendo client + unified cache),
`audio_ducking.py`, `ffmpeg_finalize.py`, and `captions.py` — all with clean,
documented, tested interfaces and zero remaining duplication to inherit.
