# Shared-Core Extraction — Design Spec

Step 2 of shared-core-extraction. Covers `docu_studio/common/` layout and, per
family, exact repoint plan for Shorts and Slideshow. Based on the actual diff in
`2026-07-12-shared-core-inventory.md` — read that first for the "why."

Test-file policy (user decision): old per-feature test files get their imports
repointed to `common/`, logic/assertions untouched. Old duplicated source files
are then fully deleted, per task instructions. No re-export shims.

---

## Module layout

```
docu_studio/common/
├── __init__.py                empty, matches slideshow/'s convention
├── resilient_download.py      family 1
├── music_jamendo.py           family 2 (Jamendo client + cache only)
├── audio_ducking.py           family 3
├── captions.py                family 4 (+ WordTiming, + Tier-3 estimator, family 6)
└── ffmpeg_finalize.py         family 5
```

Six families collapse to five files: family 6 (Tier-3 estimator) lives in
`captions.py` since its only consumer is caption generation and it's tiny —
a separate file would be a single 15-line module for no reason (CLAUDE.md
simplicity rule). `WordTiming` also lives in `captions.py` since it's the
shared contract type between the estimator and the renderer.

No `common/tests` — new/updated tests stay under `tests/unit/`, matching the
existing flat layout (no per-package test subdirs today).

---

## Family 1 — resilient downloading → `common/resilient_download.py`

**Moves verbatim:** `BROWSER_USER_AGENT`, `_CONNECT_TIMEOUT_SECONDS`,
`_READ_TIMEOUT_SECONDS`, `_MAX_ATTEMPTS`, `_BACKOFF_BASE_SECONDS`,
`_BACKOFF_JITTER_SECONDS`, `_RETRIABLE_STATUS_CODES`,
`_SAME_HOST_DELAY_RANGE_SECONDS`, `build_download_session()`, `_is_retriable()`.

**Function rename:** `download_clip_resilient`/`download_photo_resilient` →
one shared `download_resilient(session, url, dest, last_request_at=None) -> str`.
Neither name is more "correct" than the other; picking a neutral name avoids
favoring one feature's vocabulary.

**Stays put (feature-specific, not moved):**
- `fetch_topic_images()`, `_dedup_key()`, `_MAX_POOL_MULTIPLIER` stay in
  `slideshow_photo_download.py`, now importing `build_download_session`/
  `download_resilient` from `common/`.
- Shorts' `_collect_clips_per_sentence`/`_collect_clips` in `shorts_assembly.py`
  stay as-is, importing `download_resilient` in place of `download_clip_resilient`.
- The pre-existing `_collect_clips` non-resilient-download quirk (calls
  `pipeline.stages.footage_assembly.download_clip` instead) is **not touched** —
  out of scope, flagged in inventory only.

**Repoint:**
- Shorts: `shorts_assembly.py` imports change from
  `docu_studio.shorts.shorts_footage_download` to `docu_studio.common.resilient_download`.
  `shorts_footage_download.py` is deleted (nothing else in it).
- Slideshow: `slideshow_photo_download.py` keeps its file (houses
  `fetch_topic_images`), but its `build_download_session`/`_is_retriable`/
  `download_photo_resilient` definitions are deleted and replaced with an
  import from `common/`.

**Test repoint:** `tests/unit/test_shorts_footage_download.py` imports move to
`docu_studio.common.resilient_download`; function-name references update to
`download_resilient`. Any slideshow-side tests covering
`build_download_session`/`_is_retriable` (currently exercised indirectly via
`fetch_topic_images` tests, per the inventory — confirm during migration) get
the same import repoint.

---

## Family 2 — music: Jamendo client + cache → `common/music_jamendo.py`

**Moves verbatim:** `JAMENDO_API_URL`, `DEFAULT_MUSIC_MOOD`, `_REQUEST_TIMEOUT`,
`_MAX_TRACK_DURATION`, `music_cache_dir()`, `safe_cache_filename()`,
`JamendoMusicProvider` (the class is logic-identical between the two files;
Shorts' version sets `bpm=None` on every candidate it builds — see below).

**Cache dirname unification:** `_MUSIC_CACHE_DIRNAME` becomes a single
`"music_cache"` constant in `common/`. Per the inventory, the two caches are
structurally compatible (same key scheme, same stored format) — this is a safe
merge, not a data migration. Shorts and Slideshope share one cache dir after
this change; a Jamendo track fetched by one feature is a cache hit for the
other if titles match. This is a deliberate behavior change (positive: fewer
redundant downloads) — call it out explicitly in the handoff report.

**`TrackCandidate` — kept as one shared shape, not two.** Current Shorts
`TrackCandidate` has `bpm: int | None = None`; Slideshow's doesn't. Shared
dataclass keeps `bpm: int | None = None` (default None costs Slideshow
nothing — it never reads the field). `source` default stays a
constructor-supplied string, not hardcoded on the dataclass, since Shorts uses
`"local"`/`"jamendo"` and Slideshow uses `"local_folder"`/`"jamendo"` — callers
already pass `source=` explicitly at every construction site in both files, so
dropping the field default to `None`-requiring-explicit-set is fine.

**`resolve_music_track()` — NOT unified into one shared function.** The
inventory is explicit that the bpm-carrying vs bpm-less return shapes are a
real fork (Shorts feeds bpm into beat-sync; Slideshow has no beat-sync
concept), and the two functions differ in local-provider wiring (`local_folder`
param, provider-name validation, call-site layer). Forcing one signature would
mean Slideshow's runner either fabricates a fake bpm slot or Shorts loses its
beat-sync input — both worse than keeping two thin wrappers. Each
`resolve_music_track()` stays in its own file (`music_providers.py`,
`slideshow_music.py`), now built from the shared `JamendoMusicProvider` +
`TrackCandidate` + cache helpers imported from `common/`.

**Stays put (feature-specific, not moved):**
- `LocalMusicProvider` + `music_library.py` (Shorts' manifest-driven source) —
  untouched, different data model from Slideshow's folder scan.
- `LocalFolderMusicProvider` (Slideshow) — untouched.
- Both `resolve_music_track()` functions — untouched in control flow, just
  repointed to import the shared Jamendo/cache pieces.

**Repoint:**
- `docu_studio/shorts/music_providers.py`: delete local `JamendoMusicProvider`,
  `music_cache_dir`, `safe_cache_filename`, `JAMENDO_API_URL`,
  `DEFAULT_MUSIC_MOOD`, `_REQUEST_TIMEOUT`, `_MAX_TRACK_DURATION`; import them
  from `docu_studio.common.music_jamendo`. `TrackCandidate` imports from
  `common/` too (single canonical definition — Shorts' `LocalMusicProvider`
  and `resolve_music_track` both reference it).
- `docu_studio/slideshow/slideshow_music.py`: same deletions, same imports
  from `common/`.

**Test repoint:** `test_shorts_music_providers.py` and `test_slideshow_music.py`
import `JamendoMusicProvider`/`TrackCandidate`/`music_cache_dir`/
`safe_cache_filename` from `docu_studio.common.music_jamendo` instead of their
feature module; assertions on cache-dir path need updating to expect
`"music_cache"` instead of `"shorts_music_cache"`/`"slideshow_music_cache"`
(a real, intentional assertion change — not a mechanical rename — flag this
line in the migration task so it isn't missed as "just an import fix").

---

## Family 3 — audio ducking / sidechain → `common/audio_ducking.py`

**Moves verbatim, no adaptation:** `_FADE_SECONDS`, `_MUSIC_BASELINE_DB`,
`build_ducking_filtergraph(video_duration: float) -> str`. Byte-for-byte
identical today between the two files — this is the single cleanest family in
the whole inventory.

**`mix_music_bed()` stays in each `*_ffmpeg.py` file** (`ShortsFFmpeg`,
`SlideshowFFmpeg`) — it's a method on each subclass, not a free function, and
the two subclasses intentionally differ in error-handling at their call sites
(Shorts wraps in try/except and falls back to unmixed narration; Slideshow
doesn't). Only the `build_ducking_filtergraph` import inside each
`mix_music_bed()` method changes, from
`docu_studio.shorts.shorts_audio_mix`/`docu_studio.slideshow.slideshow_audio_mix`
to `docu_studio.common.audio_ducking`.

**Deleted entirely:** `shorts_audio_mix.py`, `slideshow_audio_mix.py` — nothing
left in either file once `build_ducking_filtergraph` moves out.

**Test repoint:** `test_shorts_audio_mix.py`, `test_slideshow_audio_mix.py`
import `build_ducking_filtergraph` from `docu_studio.common.audio_ducking`;
no assertion changes (filtergraph string output is identical).

---

## Family 4 — caption/ASS generation → `common/captions.py`

This is the one family where "adopt the more general form" needs an explicit
addition, not a pure lift, per the inventory's finding that Slideshow's
version has no `punch_window` support at all.

**Shared module contains:**
- `WordTiming` (single canonical dataclass — currently defined twice with
  identical fields in `capability_resolvers.py` and `slideshow_captions.py`).
- `estimate_word_timestamps(script_text, duration) -> list[WordTiming]`
  (family 6 — the Tier-3 estimator, verbatim-identical in both places today).
- `group_words`, `_escape_ass_text`, `_format_ass_time`, `_render_group_text` —
  verbatim, all four are logic-identical already.
- `_ASS_HEADER_TEMPLATE`, `_MIN_GROUP`, `_MAX_GROUP`, `_MIN_WORD_DURATION`,
  `_FONT_NAME`, `_SAFE_AREA_BOTTOM_FRACTION = 0.22` — verbatim (Slideshow's
  fraction-based margin, not Shorts' baked-pixel version — see signature below).
- `generate_ass(timings, out_width, out_height, audio_duration=None, punch_window=None) -> str`
  and `write_ass_file(timings, output_path, out_width, out_height, audio_duration=None, punch_window=None) -> None`
  — Slideshow's width/height-parameterized signature, **with `punch_window`
  added back in** (ported from Shorts' version, ~20 lines of event
  split/clamp/drop logic, inserted unchanged). Default `None` for both new
  Slideshow callers (identical to Slideshow's current behavior — zero
  behavior change there) and existing Shorts callers (which pass their
  concrete `punch_window` value, same as today).

**Repoint — Shorts (`shorts_assembly.py`, `capability_resolvers.py`):**
- `capability_resolvers.py` deletes its local `WordTiming` and
  `estimate_word_timestamps`, imports both from `docu_studio.common.captions`.
  Its own tier-resolution logic (`_tier1_native_timestamps`,
  `_tier2_whisper_alignment`, `get_word_timestamps`, `resolve_beat_grid`) is
  **untouched** — per inventory, this system has no Slideshow duplicate and
  stays Shorts-only.
- `shorts_assembly.py`'s `write_ass_file(timestamps, ass_path, audio_duration=audio_duration, punch_window=punch_window)`
  call becomes `write_ass_file(timestamps, ass_path, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=audio_duration, punch_window=punch_window)`
  — `SHORTS_WIDTH`/`SHORTS_HEIGHT` imported from `shorts_config.py` (already
  imported elsewhere in the file; confirm at migration time) instead of being
  baked into the caption module.
- `shorts_captions.py` is deleted entirely once its contents move to `common/`.

**Repoint — Slideshow (`slideshow_assembly.py`):**
- `from docu_studio.slideshow.slideshow_captions import estimate_word_timestamps, write_ass_file`
  becomes `from docu_studio.common.captions import estimate_word_timestamps, write_ass_file`.
  Call site `write_ass_file(timings, ass_path, out_width, out_height, audio_duration)`
  is unchanged (positional args already match the shared signature; the new
  `punch_window` param defaults to `None`, which is exactly what Slideshow
  wants — no call-site change needed there beyond the import).
- `slideshow_captions.py` is deleted entirely.

**Test repoint:** `test_shorts_captions.py` and `test_slideshow_captions.py`
import from `docu_studio.common.captions` instead of their feature modules;
`test_shorts_captions.py`'s `from docu_studio.shorts.capability_resolvers import WordTiming`
also moves to `docu_studio.common.captions`. No assertion changes expected —
output strings are unchanged (Shorts still gets its punch_window behavior,
Slideshow still gets its parameterized dimensions).

---

## Family 5 — ffmpeg finalize suffix → `common/ffmpeg_finalize.py`

**Moves verbatim:** `_SAR_PIXFMT_SUFFIX = "setsar=1,format=yuv420p"` and a
module-level function `finalize_filter(filter_chain: str) -> str` (currently a
`@staticmethod` on each `*FFmpeg` class — becomes a plain function since it
has no dependency on `self`/instance state in either implementation).

**Repoint:**
- `ShortsFFmpeg._finalize_filter` and `SlideshowFFmpeg._finalize_filter`
  methods are deleted; every call site that did `self._finalize_filter(...)`
  changes to a direct call to the imported `finalize_filter(...)` (four call
  sites in `shorts_ffmpeg.py`: lines 255, 301, 326, 383; four in
  `slideshow_ffmpeg.py`: lines 81 [inline constant use, not the helper —
  becomes `from docu_studio.common.ffmpeg_finalize import _SAR_PIXFMT_SUFFIX`
  or inlines the constant directly if it's only used in the f-string there],
  124, 184, 218).
- Local `_SAR_PIXFMT_SUFFIX` definitions in both `shorts_ffmpeg.py` and
  `slideshow_ffmpeg.py` are deleted, replaced by the `common/` import.

**Not touched:** crossfade/xfade logic in `slideshow_ffmpeg.py`
(`_xfade_offsets`, `concat_segments_with_xfade`) — confirmed Slideshow-only,
no Shorts duplicate to extract against, stays exactly where it is.

**Test repoint:** no dedicated `_finalize_filter`/`_SAR_PIXFMT_SUFFIX` unit
test file found in the inventory pass — verify during migration whether any
existing ffmpeg test asserts on the literal `"setsar=1,format=yuv420p"`
substring in filter output; if so, repoint the constant's source import,
not the assertion value (string is unchanged).

---

## Cross-family notes

- **No `common/` module imports `shorts/` or `slideshow/`** — dependency
  direction is one-way (`shorts/`, `slideshow/` → `common/`), matching the
  existing "no cross-imports between shorts/ and slideshow/" discipline the
  duplication itself was protecting.
- **`shorts_ffmpeg.py`'s separate `SHORTS_WIDTH=1080`/`SHORTS_HEIGHT=1920`
  constants** (lines 28-29, distinct from `shorts_config.py`'s own copy) are
  a **pre-existing, unrelated duplication** — not part of any family above,
  not touched by this extraction. Flagged for a future cleanup pass, not this one.
- **Migration order** (task-plan detail, not a design decision, but noted
  here for sequencing rationale): families 3 and 5 are the lowest-risk
  (verbatim, no signature changes) and should go first to prove out the
  extract → repoint → verify → delete rhythm before tackling family 4 (has a
  real signature addition) and family 2 (has a real behavior change — cache
  merge).

## Self-review

- Checked: does any shared function assume a caller context that doesn't
  hold for both features? `finalize_filter` — no, pure string function.
  `download_resilient` — no, pure session/url/dest. `build_ducking_filtergraph`
  — no, pure duration→string. `generate_ass`/`write_ass_file` — needed the
  `punch_window` addition to hold for both; done above. `JamendoMusicProvider`
  — no, pure client_id/query→candidates.
- Checked: does the cache-dir merge change on-disk behavior a user could
  notice? Yes — first run after this migration, both features start reading/
  writing `music_cache/` instead of their separate dirs; old
  `shorts_music_cache/`/`slideshow_music_cache/` directories become orphaned
  (not deleted, not migrated — just unused). Low risk (it's a cache, safe to
  leave stale), but calling it out explicitly rather than burying it.
- Uncertain: whether any test beyond the ones grepped so far asserts on
  cache-dirname strings or the literal SAR/pixfmt substring — flagged as
  "verify during migration" above rather than assumed either way.
