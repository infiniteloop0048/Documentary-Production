# Shorts: Video vs. Images Footage Source — Design Spec

**Date:** 2026-07-20
**Status:** Approved
**Scope:** Add a second footage-source option to the Short/Reel pipeline: "Images" (stock
photos animated with Ken Burns motion), alongside the existing "Video" (stock footage clips)
option. The rest of the pipeline — script generation, TTS, word-timing, sentence/segment
timing, captions, music, beat-sync, cinematic ending, concat/mux — is identical between the
two modes.

## Standing constraints (from CLAUDE.md, unchanged)

- Do not touch `pipeline/`, top-level `runner/`, existing files in `adapters/` (except adding
  new ones), `history/`, `licensing.py`, or existing test files unless fixing a genuine bug.
- Correct venv is `.venv/`, never `venv/`.
- Bump the cache-busting `?v=N` query string in `docu_studio/gui/webview_app.py` after any
  HTML/JS edit — confirmed current value `?v=15`; this change bumps it to `?v=16`.

## Core principle: identical scene-by-scene timing, different segment source

TTS synthesizes one continuous voiceover for the whole script; word-level timestamps are
resolved against that audio; `sentence_spans` + `plan_cuts` (both in the existing, unmodified
`shorts_cuts.py` / `shorts_sentence_cuts.py`) turn that into a sequence of segments whose
durations are driven entirely by the measured audio timing. **None of this changes for image
mode.** The only thing that differs per mode is what fills each segment:

- **Video mode (existing, unchanged):** a per-sentence pool of stock video clips; each segment
  gets a clip windowed/trimmed (with optional speed-ramp) to its audio-driven duration, then
  vertical-converted and Ken-Burns'd.
- **Image mode (new):** a per-sentence pool of stock photos; each segment gets a photo animated
  with Ken Burns directly to its exact audio-driven duration (no windowing/speed-ramp — a
  still has no internal motion to window or speed up).

## Investigation findings (read from real source, not assumed)

- **The photo-search infrastructure already exists, built for Slideshow, and is directly
  reusable.** `docu_studio/adapters/photos/base.py` defines `PhotoProvider` (ABC,
  `search(query: str, page: int) -> list[PhotoResult]`) and `PhotoResult` (`url`, `width`,
  `height`, `photo_id`). `pexels_photos_adapter.py` and `pixabay_photos_adapter.py` hit the
  photo endpoints of the same two services already used for video (`api.pexels.com/v1/search`
  and `pixabay.com/api/`), using the **same API keys** already cached under
  `docu_studio_pexels` / `docu_studio_pixabay` — no new credentials needed. `factory.py`'s
  `build_photo_providers(pexels_key, pixabay_key)` already exists and needs no changes. Coverr
  has no photo API, so it's simply absent from the image-mode provider list — expected, not a
  gap.
- **The image-to-video Ken Burns step already exists, built for Slideshow.**
  `docu_studio/slideshow/slideshow_ffmpeg.py`'s `apply_ken_burns_image(input_path, output_path,
  duration, direction, out_width, out_height)` takes a still straight to a duration-exact,
  dimension-exact moving clip in one ffmpeg call (internal scale+crop to aspect, 4x upscale,
  zoompan). It supports 10 directions (`in`, `out`, 4 straight pans, 4 corner zoom+pans).
  `docu_studio/slideshow/slideshow_motion.direction_for_index(index)` round-robins through all
  10 — a pure, zero-dependency function, reused directly (imported) rather than duplicated.
- **`ShortsFFmpeg` (shorts_ffmpeg.py) has no image-handling method today** — only
  `apply_ken_burns` (video→video, assumes a pre-vertical-converted input at output dimensions
  already). A new `apply_ken_burns_image` method is added to `ShortsFFmpeg`, ported from
  Slideshow's implementation, so Shorts stays self-contained (matches how `apply_ken_burns`
  already lives in `ShortsFFmpeg` rather than being imported from Slideshow).
- **Footage-pool collection in `shorts_assembly.py` is per-sentence and structurally generic.**
  `_collect_clips_per_sentence()` builds one candidate pool per sentence (from
  `script.visual_queries[i]`), plus a topic-level fallback pool, downloads everything, and
  returns `list[list[dict]]` (`{path, width, height}`) — `assemble_short()` then resolves
  per-sentence pools against the fallback and hands them to `plan_cuts`/the segment-building
  loop, all independent of what a "clip" actually is. A parallel
  `_collect_images_per_sentence()` following the exact same structure (photo search instead
  of video search; no `min_duration` filter since photos have no duration) plugs into the same
  downstream flow with zero changes to pool-resolution, `plan_cuts`, or the segment loop's
  control flow.
- **`_build_segment()` is the one place that must branch.** Currently it always does:
  get raw video duration → detect motion window → optional speed-ramp → trim → vertical-convert
  → `apply_ken_burns`. For an image clip, none of window-detection, speed-ramp, or
  vertical-convert apply or make sense (a still has no duration to window, no motion to speed
  up, and `apply_ken_burns_image` already does scale+crop internally). The fix is an early
  branch at the top of `_build_segment`, keyed off a new `"kind"` field on the pool-entry dict
  (`"video"` or `"image"`), that calls `apply_ken_burns_image` directly and returns — the
  existing video logic below it is completely untouched.
- **Loop revisit degrades gracefully, not identically.** `apply_loop_revisit`
  (`shorts_sentence_cuts.py`) operates on segment/cut planning, not on clip content — it is
  unaffected by clip type. Only the *video-specific* trick inside `_build_segment` (swapping to
  an alternate window "from the opposite end of the clip" when `avoid_start` is set, so the
  revisit doesn't show literally the same frames) has no still-image equivalent. For an image
  segment, `avoid_start` is simply ignored (the image branch returns before that code runs);
  the revisited segment still gets a different Ken Burns direction than its first occurrence
  (direction is derived from `seg.index`, which differs), so it reads as "the same subject,
  animated differently the second time" rather than a frozen repeat — a reasonable degradation,
  not a broken feature.
- **Speed ramping degrades to a silent no-op for images.** The toggle stays visible and
  functional for video mode; in image mode every segment takes the early `"kind" == "image"`
  return path in `_build_segment`, so the speed-ramp branch (and its `sped_count` bookkeeping)
  is simply never reached. No error, no dead toggle state to hide.
- **GUI wiring precedent already exists end-to-end** for exactly this kind of new
  Short/Reel-only `<select>` (the aspect-ratio field, added in the prior session): `index.html`
  has `#aspect-row` with `#shorts-aspect-select`; `app.js`'s `startConfig()` toggles row
  visibility by `mode === 'short'` and its submit handler reads `_q('shorts-aspect-select').value`
  into the `start_shorts_run` payload; `bridge.py`'s `start_shorts_run` does
  `config.get("aspect_ratio", "9:16")`. The new footage-source field follows this exact
  template.

## Changes by file

### `docu_studio/shorts/shorts_config.py`
- Add `SHORTS_FOOTAGE_SOURCES = ("video", "image")` and
  `SHORTS_DEFAULT_FOOTAGE_SOURCE = "video"`.
- Add `footage_source: str = SHORTS_DEFAULT_FOOTAGE_SOURCE` field to `ShortsConfig`, validated
  in `__post_init__` against `SHORTS_FOOTAGE_SOURCES` (same pattern as `aspect_ratio`).

### `docu_studio/adapters/footage/base.py`, video adapters
- No changes. `FootageClip` gets no new field; instead, pool-entry dicts built in
  `shorts_assembly.py` (not the adapter layer) carry the new `"kind"` marker — the
  adapter/provider layer stays exactly as-is for video.

### `docu_studio/shorts/shorts_ffmpeg.py`
- New method `apply_ken_burns_image(self, input_path, output_path, duration, direction,
  out_width, out_height)`, ported from `slideshow_ffmpeg.py`'s method of the same name
  (identical zoompan technique, identical 10-direction support). No existing method changes.

### `docu_studio/shorts/shorts_assembly.py`
- New `_photo_dedup_key(photo)`, `_search_one_photo_query(providers, query, max_per_query)`,
  and `_collect_images_per_sentence(script, providers, scene_dir, event_queue)` — structural
  mirrors of the existing `_dedup_key`, `_search_one_query`, `_collect_clips_per_sentence`,
  adapted for `PhotoProvider`/`PhotoResult` (no `min_duration` filter; downloads into
  `scene_dir / f"short_img_{i:03d}{ext}"`). Every pool-entry dict gets `"kind": "image"`.
  Existing video pool-entry dicts (built in `_collect_clips_per_sentence` and `_collect_clips`)
  get `"kind": "video"` added for symmetry.
- `assemble_short()` gains `footage_source: str = "video"` and
  `photo_providers: list[PhotoProvider] | None = None` parameters. The single call to
  `_collect_clips_per_sentence(...)` becomes a branch: `_collect_images_per_sentence(...)` when
  `footage_source == "image"`, else the existing call unchanged. Every line after that
  (pool/fallback resolution, music resolution, beat grid, `plan_cuts`, segment-building loop,
  concat, captions, mux, cinematic-ending hold) is untouched.
- `_build_segment()` gains an early branch: if `clip["kind"] == "image"`, call
  `ffmpeg.apply_ken_burns_image(clip["path"], <out>, seg.duration,
  direction_for_index(seg.index), *output_dimensions)` and return
  `(kenburns_path, sped_count, 0.0)` — before any of the existing raw-duration/window/
  speed-ramp/trim/vertical-convert/video-Ken-Burns code, which remains exactly as it is today.
- New import: `from docu_studio.slideshow.slideshow_motion import direction_for_index`.

### `docu_studio/shorts/shorts_runner.py`
- `ShortsRunner.__init__` gains `footage_source: str = "video"` (forwarded into
  `ShortsConfig(...)`) and `photo_providers: list[PhotoProvider] | None = None` (stored as
  `self.photo_providers`, defaulting to `[]`).
- `_execute()`'s call to `assemble_short(...)` passes
  `footage_source=self.config.footage_source` and `photo_providers=self.photo_providers`.

### `docu_studio/gui/bridge.py`
- `start_shorts_run`: read `footage_source = config.get("footage_source", "video")`. When
  `"image"`, build `photo_list = build_photo_providers(pexels_key or "", pixabay_key or "")`
  (new import from `docu_studio.adapters.photos.factory`); otherwise `photo_list = []`. Pass
  both `footage_source=footage_source` and `photo_providers=photo_list` into `ShortsRunner(...)`.
  The existing `footage_list` build is unchanged and still passed through unconditionally (it's
  cheap to construct — no network call happens until `.search()` — and keeping it unconditional
  avoids adding a second branch that has to stay in sync with the new one).

### `docu_studio/gui/web/index.html`
- New row `#footage-source-row` in the Short/Reel section, placed directly above
  `#aspect-row`, following the exact same `<select>` styling:
  ```html
  <div id="footage-source-row" class="mt-4" style="display:none">
    <label class="text-sm font-medium text-dim block">Footage source</label>
    <select id="shorts-footage-source-select"
      class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
      <option value="video">Video clips — stock footage</option>
      <option value="image">Images — stock photos with Ken Burns motion</option>
    </select>
  </div>
  ```

### `docu_studio/gui/web/app.js`
- `startConfig()`: add `_q('footage-source-row').style.display = mode === 'short' ? '' : 'none';`
  alongside the other `mode === 'short'` rows.
- Submit handler (`_runMode === 'short'` branch): add
  `footage_source: _q('shorts-footage-source-select').value,` to the `start_shorts_run` payload,
  alongside `aspect_ratio`.

### `docu_studio/gui/webview_app.py`
- Bump `?v=15` → `?v=16`.

## Testing

- `tests/unit/test_shorts_config.py`: `footage_source` accepted values (`"video"`, `"image"`),
  default is `"video"`, invalid value raises `ValueError`.
- `tests/unit/test_shorts_ffmpeg.py`: new test(s) for `apply_ken_burns_image` — command
  construction (loop flag, `-t` duration, zoompan filter contains expected direction-specific
  expressions), mirroring the existing `apply_ken_burns` test style.
- `tests/unit/test_shorts_assembly.py`:
  - `_collect_images_per_sentence` with a mocked `PhotoProvider` — per-sentence pools built,
    deduped by `photo_id`, fallback pool populated, `"kind": "image"` set on every entry.
  - `_build_segment` image branch — mocked `ShortsFFmpeg`; assert `apply_ken_burns_image` is
    called with the segment's duration and output dimensions, and that
    `get_duration`/`detect_motion_window`/`trim_clip`/`apply_speed_ramp`/`vertical_convert`/
    `apply_ken_burns` (the video-only methods) are **not** called.
  - `_build_segment` video branch — existing tests unchanged, confirming no regression.

## Explicitly out of scope

- No changes to `pipeline/`, `history/`, `licensing.py`, or existing test files beyond adding
  new test cases for this feature.
- No new photo provider beyond Pexels/Pixabay (matches video mode's provider set minus Coverr,
  which has no photo API).
- No change to how many images/videos are fetched per sentence (`_MAX_CANDIDATES_PER_QUERY`,
  pool-sizing constants) — image mode reuses the same constants as video mode's per-sentence
  pooling.
