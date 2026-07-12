# Shared-Core Extraction — Inventory

Step 1 of the shared-core-extraction task: an actual diff of the duplicated technique
families between Shorts and Slideshow, done before any design or code changes. Findings
below are from direct reading of both codepaths, not from session-summary recollection.

Every duplicated file pair inspected here **already contains a docstring/comment
explicitly stating it's an intentional copy**, tracing back to "the Phase 1 design
decision to defer all shared-code extraction with shorts/ until a phase actually needs
it." That phase is now.

---

## 1. Resilient downloading — CONFIRMED, clean, high-confidence extraction

`docu_studio/shorts/shorts_footage_download.py` vs `docu_studio/slideshow/slideshow_photo_download.py`

**Identical, not just similar:**
- `BROWSER_USER_AGENT` constant
- All tuning constants: `_CONNECT_TIMEOUT_SECONDS=10`, `_READ_TIMEOUT_SECONDS=30`,
  `_MAX_ATTEMPTS=3`, `_BACKOFF_BASE_SECONDS=1.5`, `_BACKOFF_JITTER_SECONDS=(0.0,0.5)`,
  `_RETRIABLE_STATUS_CODES={429,500,502,503,504}`, `_SAME_HOST_DELAY_RANGE_SECONDS=(0.2,0.5)`
- `build_download_session()` — identical body
- `_is_retriable(exc)` — byte-for-byte identical
- `download_clip_resilient` / `download_photo_resilient` — identical body: same-host
  pacing, 3-attempt retry loop with exponential backoff + jitter, streamed 65536-byte
  chunked write, identical exception/re-raise logic. Only the function name differs.

**No real behavioral differences** in the primitives themselves.

**Not identical — surrounding orchestration, correctly out of scope:**
- `fetch_topic_images()` (slideshow-only, in the same file) is feature-specific:
  photo-id dedup, pool-capping math, `list[str]`-only return. It's called **only**
  from `gui/bridge.py::Bridge.fetch_slideshow_images` — a standalone GUI preview-fetch
  RPC, not `SlideshowRunner`/`assemble_slideshow`. Neither `slideshow_runner.py` nor
  `slideshow_assembly.py` reference `requests`/`session`/download at all — images
  arrive as already-resolved local paths by the time the main pipeline touches them.
- Shorts' equivalent orchestration (`_collect_clips_per_sentence`, `_collect_clips`)
  lives in `shorts_assembly.py`, is far more elaborate (per-sentence pools, `clip_id`
  dedup, `{path,width,height}` dicts), and is genuinely feature-specific.
- **Pre-existing quirk worth flagging, not fixing**: shorts_assembly.py has *two*
  download call sites — `_collect_clips_per_sentence` (used by the live
  `assemble_short` entry point) uses `download_clip_resilient`; `_collect_clips`
  (apparently legacy/dead) calls a different, non-resilient `download_clip` from
  `pipeline.stages.footage_assembly`. Out of scope for this extraction; note it in
  the design spec so nobody accidentally "fixes" it as a side effect.

**Extraction candidate:** `BROWSER_USER_AGENT`, all tuning constants, `build_download_session()`,
`_is_retriable()`, and the resilient download function itself — verbatim, no
adaptation needed. This is the cleanest family in the inventory.

---

## 2. Music providers (local + Jamendo, with caching) — CONFIRMED, partial extraction

`docu_studio/shorts/music_providers.py` (+ `music_library.py`) vs `docu_studio/slideshow/slideshow_music.py`

**Identical — the Jamendo client and caching:**
- `JamendoMusicProvider`: `JAMENDO_API_URL`, `DEFAULT_MUSIC_MOOD="cinematic"`,
  `_REQUEST_TIMEOUT=10.0`, `_MAX_TRACK_DURATION=1200`, auth via plain `client_id`
  query param, identical search-param construction, identical empty-`audiodownload`
  filtering with the same Jamendo empty-string-vs-missing-key quirk handled the same
  way, identical broad-exception-catch → `[]` on failure.
- `music_cache_dir()` — both build from the same `platform_layer.config_dir()` base;
  only the dirname literal differs (`shorts_music_cache` vs `slideshow_music_cache`).
- `safe_cache_filename()` — byte-for-byte identical slugging function.
- Cache scheme is identical in both: key = slug of track title, value = raw Jamendo
  MP3 bytes written verbatim, **no invalidation** (an existing file is served forever).
  **The two caches are structurally compatible** — same key derivation, same stored
  format — so merging them into one cache dir is a safe data-model no-op, not a
  migration. (No design decision made here, just a fact: the data is compatible.)

**NOT identical — local-source strategy is a real architectural difference:**
- Shorts (`LocalMusicProvider` + `music_library.py`): picks from a bundled, curated
  JSON manifest (`assets/music/manifest.json`) carrying per-track `bpm` metadata.
  Never raises; degrades to `[]` on missing/malformed manifest.
- Slideshow (`LocalFolderMusicProvider`): picks from an arbitrary user-configured
  folder, filtered by extension (`.mp3/.wav/.m4a/.ogg`), no metadata, no manifest.
  Never raises; degrades to `[]` on missing/non-dir folder or `OSError`.
- These are genuinely different data sources feeding a common `TrackCandidate`-shaped
  interface, not the same code copy-pasted. `TrackCandidate` itself differs slightly:
  Shorts' has a `bpm: int | None` field, Slideshow's doesn't.

**Real behavioral differences beyond the local-source split:**
- **bpm/beat-sync coupling (biggest divergence).** Shorts' `resolve_music_track()`
  returns `tuple[path, label, bpm]`; the bpm feeds `resolve_beat_grid()` and drives
  cut-timing in `plan_sentence_scoped_cuts`. Slideshow's returns `tuple[path, label]`
  only — no beat-sync concept exists in Slideshow at all.
- Call-site layer differs: Shorts resolves music inside `assemble_short()` (assembly
  layer, deliberately early for bpm availability); Slideshow resolves it in
  `SlideshowRunner._execute()` (runner layer, one level up) and passes a bare
  `music_path: str | None` into assembly.
- `provider_name` vocabulary: Shorts accepts any string, branches only on `"jamendo"`,
  defaults `"local"`. Slideshow hard-validates against `("jamendo","local_folder")` in
  `SlideshowConfig.__post_init__`, defaults `"jamendo"`.
- `mood`: Shorts derives it from the LLM-generated script (`script.music_mood`);
  Slideshow always uses the hardcoded `DEFAULT_MUSIC_MOOD` constant (no script-derived
  mood field exists in `SlideshowConfig`).
- Error-handling shape: Shorts wraps the whole `resolve_music_track` call in
  try/except inside assembly (crashes degrade to "skip music"); Slideshow calls it
  unguarded in the runner (a resolution-level exception, not just "no track found,"
  would propagate to the runner's outer try/except as a fatal `ErrorEvent` instead of
  a graceful skip).

**Audio ducking/mixing consumed by both is a clean duplicate — see family 3.**

**Extraction candidate:** the `JamendoMusicProvider` class, `music_cache_dir()`,
`safe_cache_filename()`, and the shared `TrackCandidate`/provider-protocol shape are
safe to lift verbatim. The local-source providers stay separate (different data
models). `resolve_music_track()` itself needs to keep the bpm-carrying vs
bpm-less return shapes as a real fork, not force one shape on both callers — likely
resolved via an optional bpm field on a single shared return type, or two thin
wrappers around a shared core. Design spec needs to make this call explicitly.

---

## 3. Audio ducking / sidechain filtergraph — CONFIRMED, clean, high-confidence extraction

`docu_studio/shorts/shorts_audio_mix.py` vs `docu_studio/slideshow/slideshow_audio_mix.py`

**Identical, confirmed via diff:** the entire `build_ducking_filtergraph()` function —
same f-string template, same constants (`_FADE_SECONDS=1.0`, `_MUSIC_BASELINE_DB=-20`),
same `sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300`, same
`amix=inputs=2:duration=first:normalize=0`. Only the docstrings differ (and
slideshow's explicitly says it's a reimplementation of the shorts version).

`mix_music_bed()` (the ffmpeg-invoking wrapper, in `shorts_ffmpeg.py`/`slideshow_ffmpeg.py`)
is likewise identical: same cmd construction, same `-map [aout] -c:a aac`, same
`-stream_loop -1` on the music input, both write to a `.m4a` container (AAC-vs-mp3-muxer
constraint), no return value (writes to `output_path` as a side effect).

**One real behavioral difference — call-site error handling, not the shared logic:**
Shorts wraps its `mix_music_bed` call in try/except and falls back to unmixed
narration on any ffmpeg failure. Slideshow does not wrap it — a failure there
propagates uncaught. This is a property of each caller, not of the function being
extracted, so it doesn't block extraction — it just means the wrapping try/except
stays in each feature's assembly file after the core function moves to `common/`.

**Extraction candidate:** `build_ducking_filtergraph()` and `mix_music_bed()` are
safe to lift verbatim, unmodified.

---

## 4. Caption/ASS generation — CONFIRMED duplicated, but NOT a drop-in

`docu_studio/shorts/shorts_captions.py` vs `docu_studio/slideshow/slideshow_captions.py`

**Identical:** ASS header/style template (byte-for-byte), `group_words` (2-4 word
chunking), `_escape_ass_text`, `_format_ass_time`, `_render_group_text` (karaoke
`\t` scale/bold highlight), the gapless dialogue-timing algorithm, and all the tuning
constants (`_MIN_GROUP=2`, `_MAX_GROUP=4`, `_MIN_WORD_DURATION=0.05`,
`_FONT_NAME="DejaVu Sans"`, safe-area fraction `0.22`).

**Width/height generalization claim — CONFIRMED, precisely.** Shorts hardcodes
`SHORTS_WIDTH=1080, SHORTS_HEIGHT=1920` as module-level constants baked into
`generate_ass`/`write_ass_file` at import time. Slideshow's `generate_ass`/
`write_ass_file` take `out_width`/`out_height` as required parameters and compute
`margin_v` from a stored *fraction* of the passed height, not a baked pixel value.
This is exercised for real: Slideshow supports 9:16, 16:9, and 1:1 output, all
threaded through to caption generation. Adopting Slideshow's parameterized form as
the shared shape (shorts passes its own 1080×1920 in) is the right direction — less
duplication than the reverse, as instructed.

**BUT it is not a safe drop-in as-is — one real gap:**
- **`punch_window` is missing entirely from Slideshow's version.** Shorts'
  `generate_ass` has a `punch_window: tuple[float,float] | None` parameter with ~20
  lines of event-splitting/clamping logic for its punch-card feature. Slideshow has
  no equivalent parameter or logic — not a missing default, the feature doesn't
  exist there. If the shared module adopts Slideshow's signature verbatim, Shorts'
  punch-card captions silently break. The shared function needs `punch_window` ported
  in as an optional parameter (default `None`, which is exactly Slideshow's current
  behavior — free compatibility for Slideshow, no regression for Shorts).

**Other real differences, correctly out of scope for the caption renderer itself:**
- `WordTiming` is defined twice, structurally identical fields, but as two separate
  classes (`capability_resolvers.WordTiming` vs a local class in
  `slideshow_captions.py`). Needs one canonical shared definition.
- Timing *resolution* (as opposed to *rendering*) differs in ownership: Shorts
  separates "resolve timings" (3-tier chain in `capability_resolvers.py`) from
  "render ASS" (`shorts_captions.py`); Slideshow fuses them — it calls its own
  `estimate_word_timestamps` inline and hands the result straight to `write_ass_file`.
  This should not be forced together in the shared caption module; see family 5.
- Config-level default divergence (`captions_enabled=True` in Shorts,
  `captions=False` in Slideshow) — not caption-logic, doesn't affect extraction.

**Extraction candidate:** ASS header/style template, `group_words`,
`_escape_ass_text`, `_format_ass_time`, `_render_group_text`, the gapless timing
algorithm, and the width/height-parameterized `generate_ass`/`write_ass_file`
signature, **with `punch_window` added back in** as an optional parameter. A single
canonical `WordTiming` dataclass needs to be defined once and imported by both sides
(and by `capability_resolvers.py`).

---

## 5. FFmpeg segment finalize discipline & crossfade — SPLIT VERDICT

`setsar=1,format=yuv420p` normalize suffix:
- **CONFIRMED duplicated, clean extraction.** Identical constant
  (`_SAR_PIXFMT_SUFFIX = "setsar=1,format=yuv420p"`) and identical
  `_finalize_filter()` helper shape in both `shorts_ffmpeg.py` and
  `slideshow_ffmpeg.py`, applied after chained scale/zoompan/xfade operations to stop
  SAR drift from breaking `concat`. Tiny (2-3 lines + one constant), fully
  self-contained, safe to lift verbatim.

Crossfade/transition filtergraph (`xfade`, `concat_segments_with_xfade`):
- **NOT duplicated — exists only in Slideshow.** Shorts has zero transition concept;
  it only ever hard-concats segments. Slideshow's crossfade logic
  (`_TRANSITION_DURATION`, `_xfade_offsets`, `concat_segments_with_xfade`,
  `crossfade_segment_durations`) is real but has nothing to diff against, and it's
  entangled with Slideshow-specific segment-duration math. **Nothing to extract
  here — it stays in `slideshow/`.**

---

## 6. Word-timing tier resolution & TTS pace calibration — MOSTLY NOT DUPLICATED

Verified by search, not assumed, per the task's explicit instruction to check rather
than take the session-summary claim at face value.

**Tier-resolution system (`capability_resolvers.get_word_timestamps`, the 3-tier
fallback chain, `shorts_alignment.py`'s Whisper forced-alignment) — Shorts-only.**
Slideshow has no `tier`, `Whisper`, multi-source `WordTiming`, or alignment logic at
all. Its own module docstring says as much: the character-weighted estimate "is the
only tier here, not one of several." **Nothing to extract for the tier-resolution
machinery itself** — building it out for Slideshow would be adding a capability, not
removing duplication, and is explicitly out of scope for an extraction pass.

**One small piece genuinely is duplicated:** `estimate_word_timestamps` (the
character-length-weighted Tier-3 fallback) exists in both
`capability_resolvers.py` (as Tier 3) and `slideshow_captions.py` (as Slideshow's
only tier) — confirmed by two independent readings (the tier-resolution investigation
and the captions investigation both flagged it) as the same algorithm. Small,
self-contained, legitimate to extract on its own, decoupled from ASS rendering.

**TTS pace calibration (`shorts_tts_calibration.py`) — Shorts-only, no duplicate.**
Persisted per-(provider,voice) EMA-smoothed WPM calibration with a JSON store.
Slideshow uses a flat `SLIDESHOW_WPM = 150` constant, no persistence, no feedback
loop, no calibration file. **Nothing to extract — there is no duplicate to
de-duplicate against.**

---

## Summary table

| Family | Duplicated? | Extraction scope |
|---|---|---|
| Resilient downloading | Yes, clean | Full — verbatim |
| Music: Jamendo client + cache | Yes, clean | Full — verbatim (cache dirname can unify) |
| Music: local-source provider | No — different data models | Stays split (shorts=manifest, slideshow=folder) |
| Music: `resolve_music_track` orchestration | Partial | Shared core, bpm-shape needs explicit handling |
| Audio ducking/sidechain | Yes, clean | Full — verbatim |
| Caption/ASS generation | Yes, with a gap | Full, but must add `punch_window` back in; unify `WordTiming` |
| `setsar=1,format=yuv420p` finalize | Yes, clean | Full — verbatim (tiny) |
| Crossfade/xfade transitions | No — Slideshow-only feature | Not extracted, stays in `slideshow/` |
| Word-timing tier resolution (full system) | No — Shorts-only | Not extracted |
| `estimate_word_timestamps` (Tier 3 only) | Yes, clean | Small, standalone extraction |
| TTS pace calibration | No — Shorts-only, no duplicate | Not extracted |

Six real families to extract (down from the eight originally listed, since two —
crossfade and tier-resolution/pace-calibration — turned out not to be duplicates at
all). This confirms the task's own instruction to verify rather than assume: roughly
25% of the assumed scope wasn't actually there.
