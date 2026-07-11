# Slideshow Phase 2 — Design Spec: Topic-based Image Fetch + LLM Script Generation

## 0. Context and scope

Phase 1 (merged into branch `slideshow-phase1`, not yet merged to `main`) built a
self-contained `docu_studio/slideshow/` package: manual image upload + user-typed
script + Ken Burns motion + hard-cut assembly. Phase 2 adds two independent
capabilities on top of that, without touching Phase 1's core pipeline:

1. **Topic-based photo fetch** (Pexels/Pixabay photo search + resilient download),
   feeding the same `image_paths` list the manual upload path already produces.
2. **LLM-generated narration script**, feeding the same `script_text` string the
   manual textarea already produces.

Phase 3 (transitions, pan/rotation motion variety, captions, music) is explicitly
out of scope and untouched.

## 1. Investigation findings that shape this design

- **Phase 1's script "segmentation" is duration-only, not content-aware.**
  `slideshow_assembly.split_duration_evenly(total_duration, count)` divides the
  *audio duration* evenly across however many images exist, after the entire
  `script_text` is synthesized as one TTS call. There is no sentence-splitting, no
  per-image text extraction, and no relationship between narration content and
  which image gets which time slice — this is a deliberate Phase 1 design choice
  (see `slideshow_assembly.py` module docstring). Consequence: LLM-generated text
  needs no new segmentation logic — it becomes `script_text` and flows through the
  exact same `SlideshowConfig` → TTS → `split_duration_evenly` path manual scripts
  already use.
- **`FootageProvider`/`FootageClip` (`docu_studio/adapters/footage/base.py`) are
  duration-oriented and don't fit stills** (`FootageClip.duration`,
  `FootageProvider.search(keywords, min_duration, page)`). Photo search needs its
  own ABC, not a reuse of the video one.
- **No shared HTTP-client/API-key helper exists** across the video footage
  adapters — each (`pexels_adapter.py`, `pixabay_adapter.py`) independently wraps
  `requests.get(...)` with the `@retry` decorator from `docu_studio/retry.py` and
  near-identical inline status-code handling. The photo adapters will follow the
  same per-adapter pattern, not introduce a new shared client class (consistent
  with existing conventions; introducing one would be unrequested abstraction).
- **The resilient downloader (`docu_studio/shorts/shorts_footage_download.py`) is
  explicitly framed as shorts-only** ("This is a shorts-only concern") and the
  Phase 1 design decision was to defer all shared-infrastructure extraction with
  `shorts/` until a phase actually needs it. Phase 2 continues that: the photo
  downloader is a fresh, self-contained copy of the same hardened pattern inside
  `docu_studio/slideshow/`, not an import from `shorts/`.
- **LLM script generation has no "generate narration for N images" primitive.**
  `LLMProvider.generate_script(topic, target_words, on_diminishing_returns)` is
  the only free-text generation method. `docu_studio/shorts/shorts_script_gen.py`
  demonstrates a working technique for full prompt customization within this
  signature: it passes its entire custom instruction template as the `topic`
  argument (the Anthropic implementation just interpolates `topic` into its own
  wrapper prompt). Phase 2 reuses this technique with a different template.
- **The GUI has no "manual vs topic" toggle pattern to extend** — the task's own
  wording ("extend the existing 'topic-based' mode toggle") assumed one exists;
  it doesn't. The closest existing pattern is Documentary's separate Guided/Full
  Auto mode-select cards, but the task explicitly places the new controls "next
  to the existing script textarea" and "feeding into the same image list" —
  i.e. **additive controls on the same Slideshow config screen**, not a second
  mode card. This is simpler and matches the task's explicit wording, so that's
  what this design builds.

## 2. Topic-based photo fetch

### New package: `docu_studio/adapters/photos/`

- **`base.py`**: `PhotoResult` (frozen dataclass: `url: str, width: int,
  height: int, photo_id: str`) and `PhotoProvider(ABC)` with
  `search(query: str, page: int = 1) -> list[PhotoResult]`.
- **`pexels_photos_adapter.py`**: `PexelsPhotosAdapter(api_key)`, hits
  `https://api.pexels.com/v1/search` (the photo endpoint — distinct from the
  existing video adapter's `api.pexels.com/videos/search`), `per_page=20`,
  parses `data["photos"]` → `src.large`, `width`, `height`, `id`. Same
  `@retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)` and same
  429/401/403/400/404/timeout/connection-error handling as the existing
  `PexelsAdapter`.
- **`pixabay_photos_adapter.py`**: `PixabayPhotosAdapter(api_key)`, hits
  `https://pixabay.com/api/` (distinct from the existing video adapter's
  `pixabay.com/api/videos/`), parses `data["hits"]` → `largeImageURL`,
  `imageWidth`, `imageHeight`, `id`. Same retry/error-handling shape as the
  existing `PixabayAdapter`, including its empty-key-returns-`[]` guard.
- **`factory.py`**: `build_photo_providers(pexels_key: str, pixabay_key: str) ->
  list[PhotoProvider]` — Pexels always attempted (even with an empty key, mirroring
  the existing footage factory's behavior), Pixabay included only if its key is
  set. Order is fixed: Pexels primary, Pixabay fallback — no provider-order
  setting is added to the GUI (existing key_cache usernames `docu_studio_pexels`/
  `docu_studio_pixabay` are reused; no new keys to manage).

Reused API keys mean a user who has already configured Pexels/Pixabay for
Documentary/Shorts footage gets photo search for free — no new Settings UI.

### New module: `docu_studio/slideshow/slideshow_photo_download.py`

A fresh, self-contained copy of `shorts_footage_download.py`'s exact pattern
(same constants: `BROWSER_USER_AGENT`, `(10, 30)` connect/read timeouts, 3
attempts, `1.5 * 2**(n-1) + jitter(0, 0.5)` backoff, retriable only on
`{429, 500, 502, 503, 504}` plus connection/timeout errors, same-host pacing
`(0.2, 0.5)`), plus a new orchestration function:

```python
def fetch_topic_images(topic: str, count: int, providers: list[PhotoProvider], dest_dir: Path) -> list[str]:
```

Algorithm:
1. Query providers in order (Pexels then Pixabay if configured), page 1, until
   the candidate pool reaches `ceil(count * 1.5)` distinct photos or providers
   are exhausted (mirrors Shorts' `_MAX_POOL_MULTIPLIER = 1.5` over-fetch guard
   — enough redundancy to absorb a few failed downloads without over-fetching
   the whole provider result set).
2. Dedupe by `photo_id` (not URL — same rationale as `FootageClip.clip_id`:
   signed URLs can vary per call for the same photo).
3. Download in pool order using `download_photo_resilient` (the copied
   pattern) until `count` succeed or the pool is exhausted.
4. Zero successful downloads → raise `RuntimeError` with a clear message.
   Partial success (fewer than `count`) → return what succeeded; the caller
   surfaces "Fetched N of M images" rather than treating it as fatal, matching
   the resilience-over-perfection philosophy already used for footage in
   Shorts.

### GUI

One shared topic text input plus an image-count stepper (default 8, range
3–15) at the top of the existing images section on the Slideshow config
screen, with a "Fetch images" button. Click triggers a new synchronous
`bridge.py` method:

```python
def fetch_slideshow_images(self, topic: str, count: int) -> dict:
    # downloads to a temp dir, returns {"ok": True, "paths": [...], "message": "Fetched N of M"}
    # or {"ok": False, "error": "..."}
```

Downloaded local paths populate a thumbnail grid (select/deselect + reorder,
same up/down/remove affordance the manual image list already has) built with
the same DOM-construction style `_renderSlideshowImages()` already uses
(`textContent`, not `innerHTML` interpolation, for XSS safety). Confirmed
selections merge into the existing `_slideshowImages` array — the same array
`browseSlideshowImages()` already fills — so `validate_manual_images` at
run-start covers fetched images for free with zero new runner-side code.

**Flagged risk:** thumbnails need to render local downloaded files as `<img>`
sources inside the QtWebEngine view. This design assumes `file://` URIs work
for that (the app's own HTML is already loaded from a local file, so
same-origin local file access is plausible) but it hasn't been verified in
this codebase. This will be smoke-tested early in implementation before the
rest of the grid UI is built around it; the fallback is embedding thumbnails
as base64 data URIs instead.

## 3. LLM script generation

### New module: `docu_studio/slideshow/slideshow_script_gen.py`

```python
SLIDESHOW_WPM = 150            # matches Documentary's descriptive pace, not Shorts' 170
_DEFAULT_SECONDS_PER_IMAGE = 5.0

def target_word_count(image_count: int, seconds_per_image: float = _DEFAULT_SECONDS_PER_IMAGE, wpm: float = SLIDESHOW_WPM) -> int: ...

def generate_slideshow_script(topic: str, image_count: int, llm: LLMProvider) -> str: ...
```

`generate_slideshow_script` computes `target_words` from image count via
`target_word_count`, then calls `llm.generate_script(topic=<full instruction
template>, target_words=target_words)` — using the same "smuggle the full
prompt through the `topic` argument" technique `shorts_script_gen.py` already
uses, but with a template that explicitly asks for **even, descriptive,
documentary-style narration paced steadily across the whole script** — no
cold-open hook, no rhetorical questions, no payoff/loop structure — to keep
the tone clearly distinct from Shorts' punchy short-form copy.

No sentence-splitting or `break_into_scenes` call is needed (unlike Shorts),
since Phase 1's segmentation is duration-only, not per-sentence.

### GUI

"Generate with LLM" button next to the existing script textarea, using the
same shared topic input the image-fetch controls use. Disabled until
`_slideshowImages.length > 0`, since target length is derived from image
count (a short tooltip explains why). On click, calls a new `bridge.py`
method:

```python
def generate_slideshow_script(self, topic: str, image_count: int) -> dict:
    # builds llm the same way start_shorts_run does (s.llm_provider/s.llm_model/key_cache)
    # returns {"ok": True, "script_text": "..."} or {"ok": False, "error": "..."}
```

On success, the textarea is filled with the generated text — the user can
still hand-edit before starting the run, same as manual entry today.

## 4. Error handling

- Photo fetch: zero successful downloads → bridge returns `{"ok": False,
  "error": ...}`, shown inline near the Fetch button; grid stays empty, no
  crash. Partial success → succeeds with a "Fetched N of M" message.
- Script generation: any LLM/network failure → `{"ok": False, "error": ...}`,
  shown inline near the Generate button; textarea is left untouched (no
  partial/garbled text written).
- Both bridge methods follow the existing try/except-returns-dict convention
  already used by `start_slideshow_run`/`browse_images` — no new error-handling
  pattern introduced.

## 5. Testing

- `test_pexels_photos_adapter.py` / `test_pixabay_photos_adapter.py`: HTTP-mocked,
  mirroring the rigor of the existing (untested-in-this-investigation but
  structurally identical) video adapters — status-code handling
  (429/401/403/400/404/200), response parsing, empty-key skip for Pixabay.
- `test_photos_factory.py`: provider selection/ordering logic.
- `test_slideshow_photo_download.py`: copied test structure from
  `tests/unit/test_shorts_footage_download.py` (retry-on-transient,
  no-retry-on-4xx, session/header/timeout assertions, same-host pacing) plus
  new tests for `fetch_topic_images`'s pool-cap/dedupe/partial-success logic.
- `test_slideshow_script_gen.py`: `target_word_count` math, and
  `generate_slideshow_script` prompt construction / target_words against a
  mocked `LLMProvider`.
- No dedicated unit tests for the `Bridge.fetch_slideshow_images`/
  `Bridge.generate_slideshow_script` methods themselves — consistent with the
  existing convention (`Bridge.start_slideshow_run`/`browse_images` have no
  direct unit tests either, since they require mocking `self._window`,
  `self._settings`, and `key_cache` together). The one existing bridge test
  file, `test_bridge_duration.py`, only covers a small extracted pure
  function (`duration_to_minutes`); the real coverage for this phase's logic
  lives in `fetch_topic_images` and `generate_slideshow_script` themselves,
  tested directly as above.
- No changes to any existing test file.

## 6. Manual verification (real runs, not just logs)

Same standard as Phase 1: a real end-to-end run hitting the actual
Pexels/Pixabay photo endpoints and the actual configured LLM, extracting and
personally viewing output frames to confirm fetched images render correctly
with Ken Burns motion and that LLM-generated narration length is sensible
for the image count. GUI click-through (Fetch button → thumbnail grid →
Generate button → Start) is expected to hit the same synthetic-input
limitation documented in the Phase 1 session (X11 input not reaching the
QtWebEngine content in this sandbox) — this will be flagged the same way
rather than re-diagnosed as a bug, with a recommendation for manual
verification.

## 7. Out of scope (deferred to Phase 3 or beyond)

- Per-sentence/per-image content alignment between narration and specific
  fetched images (Phase 1's duration-only split stands unchanged).
- User-selectable photo provider order/preference.
- New API keys or Settings UI beyond what's already configured for
  Documentary/Shorts footage.
- Any pan/rotation/crossfade motion variety, captions, or music (Phase 3).
