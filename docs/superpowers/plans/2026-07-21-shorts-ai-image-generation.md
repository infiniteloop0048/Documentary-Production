# Shorts: AI-Generated Images Footage Source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third Shorts/Reel footage source, `"ai_image"`, that generates one
AI image per sentence (via OpenAI/Gemini/Replicate/fal.ai, user-selected) from a
detailed, story-aware prompt, instead of searching stock libraries — reusing the
existing Ken Burns still-image rendering pipeline unchanged.

**Architecture:** A new `docu_studio/adapters/image_gen/` package (ABC + 4 provider
adapters + a preset factory) sits alongside the existing `photos`/`footage`/`llm`
adapter packages. `shorts_script_gen.py` gains an optional style-guide LLM call plus
a richer per-sentence prompt template that emits a detailed `image_prompt` per
sentence (in addition to the existing short stock-search `title`). A new
`_collect_ai_images_per_sentence()` in `shorts_assembly.py` generates each
sentence's image, falling back to a single stock-photo search on that sentence's
existing query if generation fails. `_build_segment()` needs **no changes** — it
already renders any `"kind": "image"` pool entry via Ken Burns regardless of
whether the file was downloaded or generated.

**Tech Stack:** Python 3.11+, `openai` SDK (already a dependency, used for the
OpenAI adapter), `requests` (Gemini/Replicate/fal.ai adapters — no new SDK
dependencies), `keyring` (new credential storage), pytest + `unittest.mock.patch`
for all new tests (no live network calls).

## Global Constraints

- Do not touch `pipeline/`, top-level `runner/`, existing files in `adapters/`
  (except adding new ones), `history/`, `licensing.py`, or existing test files
  unless fixing a genuine bug.
- Correct venv is `.venv/`, never `venv/`. Run all commands as
  `.venv/bin/python -m pytest ...` / `.venv/bin/python -m ...`.
- Bump the cache-busting `?v=N` query string in `docu_studio/gui/webview_app.py`
  after any HTML/JS edit — current value `?v=16`, this plan bumps it to `?v=17`.
- No real, paid API calls during implementation — every new adapter is tested with
  `unittest.mock.patch` on `requests`/the `OpenAI` client class, matching the
  existing `test_deepgram_adapter.py` / `test_openai_adapter.py` conventions. No
  live end-to-end run happens as part of this plan.
- `docu_studio/gui/*` is excluded from coverage (`pyproject.toml`
  `[tool.coverage.run] omit`) and has no existing unit-test suite — GUI/bridge
  tasks in this plan are verified by manual `grep`-based wiring checks, matching
  the precedent set by the prior Shorts footage-source session (see spec's
  Investigation Findings).
- `ShortsRunner` has no dedicated unit-test file today (`test_shorts_runner.py`
  does not exist) — its wiring task in this plan follows that existing precedent
  and is verified via the full regression suite (Task 12) rather than a new
  dedicated test file.

---

### Task 1: `key_cache.py` — new credential slots

**Files:**
- Modify: `docu_studio/config/key_cache.py:10-22`
- Test: `tests/unit/test_config_key_cache.py` (new file)

**Interfaces:**
- Produces: `_USERNAMES` list gains `"docu_studio_gemini"`, `"docu_studio_replicate"`,
  `"docu_studio_fal"` — read later by `bridge.py` (Task 11) via `key_cache.get(...)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config_key_cache.py`:

```python
"""Unit tests for the new AI-image-generation credential slots in key_cache."""
from __future__ import annotations

from docu_studio.config.key_cache import _USERNAMES


class TestImageGenCredentialSlots:
    def test_gemini_replicate_fal_usernames_present(self) -> None:
        assert "docu_studio_gemini" in _USERNAMES
        assert "docu_studio_replicate" in _USERNAMES
        assert "docu_studio_fal" in _USERNAMES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_config_key_cache.py -v`
Expected: FAIL — `assert "docu_studio_gemini" in _USERNAMES` (not present yet).

- [ ] **Step 3: Add the three usernames**

In `docu_studio/config/key_cache.py`, extend `_USERNAMES`:

```python
_USERNAMES = [
    "docu_studio_anthropic",
    "docu_studio_openai",
    "docu_studio_openrouter",
    "docu_studio_groq",
    "docu_studio_elevenlabs",
    "docu_studio_deepgram_key",
    "docu_studio_pexels",
    "docu_studio_pixabay",
    "docu_studio_coverr",
    "docu_studio_serper",
    "docu_studio_jamendo",
    "docu_studio_gemini",
    "docu_studio_replicate",
    "docu_studio_fal",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_config_key_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docu_studio/config/key_cache.py tests/unit/test_config_key_cache.py
git commit -m "feat(config): add credential slots for Gemini/Replicate/fal.ai"
```

---

### Task 2: `ImageGenProvider` ABC + OpenAI adapter

**Files:**
- Create: `docu_studio/adapters/image_gen/__init__.py` (empty, matches
  `adapters/photos/__init__.py`)
- Create: `docu_studio/adapters/image_gen/base.py`
- Create: `docu_studio/adapters/image_gen/openai_adapter.py`
- Test: `tests/unit/test_image_gen_openai_adapter.py`

**Interfaces:**
- Produces: `ImageGenProvider(ABC)` with abstract method
  `generate(self, prompt: str, width: int, height: int) -> bytes` — every later
  adapter (Tasks 3-5) implements this exact signature. `OpenAIImageGenAdapter(api_key: str, model: str = "gpt-image-1")`.

- [ ] **Step 1: Create the package and ABC (no test needed — pure interface)**

Create `docu_studio/adapters/image_gen/__init__.py` (empty file).

Create `docu_studio/adapters/image_gen/base.py`:

```python
"""ImageGenProvider ABC — text-to-image generation, distinct from PhotoProvider
(docu_studio/adapters/photos/base.py). A search returns a pool of candidates to
choose from; text-to-image produces exactly one image per prompt, so there is no
candidate-pool concept here."""
from __future__ import annotations

from abc import ABC, abstractmethod


class ImageGenProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        """Generate one image matching *prompt*, sized as close to *width* x
        *height* as the provider supports, and return raw image bytes (PNG/JPEG).
        Raises on failure — callers decide fallback behavior."""
```

- [ ] **Step 2: Write the failing test for the OpenAI adapter**

Create `tests/unit/test_image_gen_openai_adapter.py`:

```python
"""Unit tests for OpenAIImageGenAdapter. Mirrors the existing
tests/integration/test_openai_adapter.py convention: the OpenAI SDK client class
is patched, no real network calls happen."""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.image_gen.openai_adapter import OpenAIImageGenAdapter

_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake image bytes"


def _make_adapter() -> tuple[OpenAIImageGenAdapter, MagicMock]:
    mock_client = MagicMock()
    with patch("docu_studio.adapters.image_gen.openai_adapter.OpenAI", return_value=mock_client):
        adapter = OpenAIImageGenAdapter(api_key="test-key")
    return adapter, mock_client


def _image_response(b64_json: str | None) -> MagicMock:
    resp = MagicMock()
    resp.data = [MagicMock(b64_json=b64_json)]
    return resp


class TestGenerate:
    def test_returns_decoded_bytes(self) -> None:
        adapter, mock_client = _make_adapter()
        encoded = base64.b64encode(_FAKE_PNG_BYTES).decode("ascii")
        mock_client.images.generate.return_value = _image_response(encoded)

        result = adapter.generate("a red bicycle", 1080, 1920)

        assert result == _FAKE_PNG_BYTES

    def test_passes_prompt_and_model_to_api(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.images.generate.return_value = _image_response(
            base64.b64encode(_FAKE_PNG_BYTES).decode("ascii")
        )

        adapter.generate("a red bicycle", 1080, 1920)

        call_kwargs = mock_client.images.generate.call_args.kwargs
        assert call_kwargs["prompt"] == "a red bicycle"
        assert call_kwargs["model"] == "gpt-image-1"
        assert call_kwargs["n"] == 1

    def test_portrait_dimensions_request_portrait_size(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.images.generate.return_value = _image_response(
            base64.b64encode(_FAKE_PNG_BYTES).decode("ascii")
        )
        adapter.generate("prompt", 1080, 1920)
        assert mock_client.images.generate.call_args.kwargs["size"] == "1024x1536"

    def test_landscape_dimensions_request_landscape_size(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.images.generate.return_value = _image_response(
            base64.b64encode(_FAKE_PNG_BYTES).decode("ascii")
        )
        adapter.generate("prompt", 1920, 1080)
        assert mock_client.images.generate.call_args.kwargs["size"] == "1536x1024"

    def test_square_dimensions_request_square_size(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.images.generate.return_value = _image_response(
            base64.b64encode(_FAKE_PNG_BYTES).decode("ascii")
        )
        adapter.generate("prompt", 1080, 1080)
        assert mock_client.images.generate.call_args.kwargs["size"] == "1024x1024"

    def test_raises_when_no_image_data_returned(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.images.generate.return_value = _image_response(None)
        with pytest.raises(RuntimeError, match="no image data"):
            adapter.generate("prompt", 1080, 1920)


class TestRetryBehavior:
    def test_retries_on_transient_failure_then_succeeds(self) -> None:
        adapter, mock_client = _make_adapter()
        encoded = base64.b64encode(_FAKE_PNG_BYTES).decode("ascii")
        mock_client.images.generate.side_effect = [
            RuntimeError("rate limited"),
            _image_response(encoded),
        ]
        with patch("time.sleep"):
            result = adapter.generate("prompt", 1080, 1920)
        assert result == _FAKE_PNG_BYTES
        assert mock_client.images.generate.call_count == 2

    def test_raises_after_exhausting_retries(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.images.generate.side_effect = RuntimeError("persistent failure")
        with patch("time.sleep"), pytest.raises(RuntimeError, match="persistent failure"):
            adapter.generate("prompt", 1080, 1920)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_openai_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docu_studio.adapters.image_gen.openai_adapter'`

- [ ] **Step 4: Implement `OpenAIImageGenAdapter`**

Create `docu_studio/adapters/image_gen/openai_adapter.py`:

```python
"""OpenAI GPT-Image-1 adapter — text-to-image, distinct from
docu_studio/adapters/llm/openai_adapter.py (chat completions)."""
from __future__ import annotations

import base64

from openai import OpenAI

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

# GPT-Image-1 only supports these three fixed sizes — request whichever is
# closest to the caller's aspect ratio; the existing Ken Burns scale+crop step
# handles the final exact fit regardless of provider-returned pixel size.
_SIZE_SQUARE = "1024x1024"
_SIZE_PORTRAIT = "1024x1536"
_SIZE_LANDSCAPE = "1536x1024"


def _closest_size(width: int, height: int) -> str:
    if width == height:
        return _SIZE_SQUARE
    return _SIZE_PORTRAIT if height > width else _SIZE_LANDSCAPE


class OpenAIImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str = "gpt-image-1") -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=_closest_size(width, height),
            n=1,
        )
        b64 = response.data[0].b64_json
        if not b64:
            raise RuntimeError("OpenAI image generation returned no image data")
        return base64.b64decode(b64)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_openai_adapter.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add docu_studio/adapters/image_gen/ tests/unit/test_image_gen_openai_adapter.py
git commit -m "feat(image-gen): add ImageGenProvider ABC and OpenAI GPT-Image-1 adapter"
```

---

### Task 3: Gemini adapter (Nano Banana / Nano Banana Pro)

**Files:**
- Create: `docu_studio/adapters/image_gen/gemini_adapter.py`
- Test: `tests/unit/test_image_gen_gemini_adapter.py`

**Interfaces:**
- Consumes: `ImageGenProvider` (Task 2).
- Produces: `GeminiImageGenAdapter(api_key: str, model: str)` — `model` is either
  `"gemini-2.5-flash-image"` (Nano Banana) or `"gemini-3-pro-image-preview"` (Nano
  Banana Pro), passed in by the factory (Task 6).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_image_gen_gemini_adapter.py`:

```python
"""Unit tests for GeminiImageGenAdapter. requests.post is mocked throughout;
no real network calls happen."""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
import requests

from docu_studio.adapters.image_gen.gemini_adapter import GeminiImageGenAdapter

_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake image bytes"


def _success_response(image_bytes: bytes = _FAKE_PNG_BYTES) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image_bytes).decode("ascii")}}
                    ]
                }
            }
        ]
    }
    return resp


class TestGenerate:
    def test_returns_decoded_bytes(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-2.5-flash-image")
        with patch("docu_studio.adapters.image_gen.gemini_adapter.requests.post", return_value=_success_response()):
            result = adapter.generate("a red bicycle", 1080, 1920)
        assert result == _FAKE_PNG_BYTES

    def test_posts_to_model_specific_endpoint_with_api_key_header(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-3-pro-image-preview")
        with patch("docu_studio.adapters.image_gen.gemini_adapter.requests.post", return_value=_success_response()) as mock_post:
            adapter.generate("prompt", 1080, 1920)
        args, kwargs = mock_post.call_args
        assert "gemini-3-pro-image-preview:generateContent" in args[0]
        assert kwargs["headers"]["x-goog-api-key"] == "test-key"

    def test_sends_prompt_and_aspect_ratio(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-2.5-flash-image")
        with patch("docu_studio.adapters.image_gen.gemini_adapter.requests.post", return_value=_success_response()) as mock_post:
            adapter.generate("a red bicycle", 1080, 1920)
        body = mock_post.call_args.kwargs["json"]
        assert body["contents"][0]["parts"][0]["text"] == "a red bicycle"
        assert body["generationConfig"]["imageConfig"]["aspectRatio"] == "9:16"
        assert body["generationConfig"]["responseModalities"] == ["IMAGE"]

    def test_landscape_dimensions_request_16_9(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-2.5-flash-image")
        with patch("docu_studio.adapters.image_gen.gemini_adapter.requests.post", return_value=_success_response()) as mock_post:
            adapter.generate("prompt", 1920, 1080)
        assert mock_post.call_args.kwargs["json"]["generationConfig"]["imageConfig"]["aspectRatio"] == "16:9"

    def test_square_dimensions_request_1_1(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-2.5-flash-image")
        with patch("docu_studio.adapters.image_gen.gemini_adapter.requests.post", return_value=_success_response()) as mock_post:
            adapter.generate("prompt", 1080, 1080)
        assert mock_post.call_args.kwargs["json"]["generationConfig"]["imageConfig"]["aspectRatio"] == "1:1"

    def test_raises_on_non_200_status(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-2.5-flash-image")
        resp = MagicMock(status_code=400, text="bad request")
        with patch("docu_studio.adapters.image_gen.gemini_adapter.requests.post", return_value=resp), \
             patch("time.sleep"), \
             pytest.raises(RuntimeError, match="400"):
            adapter.generate("prompt", 1080, 1920)

    def test_raises_when_no_inline_image_data_present(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-2.5-flash-image")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "sorry, I can't do that"}]}}]}
        with patch("docu_studio.adapters.image_gen.gemini_adapter.requests.post", return_value=resp), \
             patch("time.sleep"), \
             pytest.raises(RuntimeError, match="no image data"):
            adapter.generate("prompt", 1080, 1920)


class TestRetryBehavior:
    def test_retries_on_connection_error_then_succeeds(self) -> None:
        adapter = GeminiImageGenAdapter(api_key="test-key", model="gemini-2.5-flash-image")
        with patch(
            "docu_studio.adapters.image_gen.gemini_adapter.requests.post",
            side_effect=[requests.exceptions.ConnectionError("reset"), _success_response()],
        ), patch("time.sleep"):
            result = adapter.generate("prompt", 1080, 1920)
        assert result == _FAKE_PNG_BYTES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_gemini_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `GeminiImageGenAdapter`**

Create `docu_studio/adapters/image_gen/gemini_adapter.py`:

```python
"""Google Gemini image generation adapter — covers both "Nano Banana"
(gemini-2.5-flash-image) and "Nano Banana Pro" (gemini-3-pro-image-preview);
model id is passed in by the caller, this class doesn't hardcode a tier."""
from __future__ import annotations

import base64

import requests

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _aspect_ratio(width: int, height: int) -> str:
    if width == height:
        return "1:1"
    return "9:16" if height > width else "16:9"


class GeminiImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = requests.post(
            _API_URL_TEMPLATE.format(model=self._model),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    "imageConfig": {"aspectRatio": _aspect_ratio(width, height)},
                },
            },
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Gemini image generation failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise RuntimeError("Gemini image generation returned no image data")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_gemini_adapter.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/adapters/image_gen/gemini_adapter.py tests/unit/test_image_gen_gemini_adapter.py
git commit -m "feat(image-gen): add Gemini Nano Banana / Nano Banana Pro adapter"
```

---

### Task 4: Replicate adapter (FLUX, SDXL)

**Files:**
- Create: `docu_studio/adapters/image_gen/replicate_adapter.py`
- Test: `tests/unit/test_image_gen_replicate_adapter.py`

**Interfaces:**
- Consumes: `ImageGenProvider` (Task 2).
- Produces: `ReplicateImageGenAdapter(api_key: str, model: str)` — `model` is an
  `"owner/name"` string, e.g. `"black-forest-labs/flux-schnell"`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_image_gen_replicate_adapter.py`:

```python
"""Unit tests for ReplicateImageGenAdapter. requests.post/get are mocked
throughout; no real network calls happen. Replicate's API is asynchronous —
create a prediction, poll until it succeeds, then download the output URL —
so tests cover both the immediate-success and poll-then-succeed paths."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.image_gen.replicate_adapter import ReplicateImageGenAdapter

_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake image bytes"


def _prediction_response(status_code: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _image_download_response() -> MagicMock:
    resp = MagicMock()
    resp.content = _FAKE_PNG_BYTES
    resp.raise_for_status = MagicMock()
    return resp


class TestGenerate:
    def test_immediate_success_downloads_output(self) -> None:
        adapter = ReplicateImageGenAdapter(api_key="test-key", model="black-forest-labs/flux-schnell")
        create_resp = _prediction_response(201, {
            "status": "succeeded",
            "output": ["https://replicate.delivery/out.png"],
            "urls": {"get": "https://api.replicate.com/v1/predictions/abc"},
        })
        with patch("docu_studio.adapters.image_gen.replicate_adapter.requests.post", return_value=create_resp), \
             patch("docu_studio.adapters.image_gen.replicate_adapter.requests.get", return_value=_image_download_response()):
            result = adapter.generate("a red bicycle", 1080, 1920)
        assert result == _FAKE_PNG_BYTES

    def test_posts_to_model_specific_endpoint_with_bearer_token(self) -> None:
        adapter = ReplicateImageGenAdapter(api_key="test-key", model="black-forest-labs/flux-schnell")
        create_resp = _prediction_response(201, {
            "status": "succeeded", "output": ["https://x/out.png"], "urls": {"get": "https://x/get"},
        })
        with patch("docu_studio.adapters.image_gen.replicate_adapter.requests.post", return_value=create_resp) as mock_post, \
             patch("docu_studio.adapters.image_gen.replicate_adapter.requests.get", return_value=_image_download_response()):
            adapter.generate("a red bicycle", 1080, 1920)
        args, kwargs = mock_post.call_args
        assert "black-forest-labs/flux-schnell/predictions" in args[0]
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert kwargs["json"]["input"]["prompt"] == "a red bicycle"
        assert kwargs["json"]["input"]["aspect_ratio"] == "9:16"

    def test_polls_when_prediction_still_processing(self) -> None:
        adapter = ReplicateImageGenAdapter(api_key="test-key", model="black-forest-labs/flux-schnell")
        create_resp = _prediction_response(201, {
            "status": "processing", "urls": {"get": "https://api.replicate.com/v1/predictions/abc"},
        })
        poll_resp = _prediction_response(200, {
            "status": "succeeded", "output": ["https://x/out.png"], "urls": {"get": "https://x/get"},
        })
        with patch("docu_studio.adapters.image_gen.replicate_adapter.requests.post", return_value=create_resp), \
             patch("docu_studio.adapters.image_gen.replicate_adapter.requests.get", side_effect=[poll_resp, _image_download_response()]), \
             patch("time.sleep"):
            result = adapter.generate("prompt", 1080, 1920)
        assert result == _FAKE_PNG_BYTES

    def test_raises_when_prediction_fails(self) -> None:
        adapter = ReplicateImageGenAdapter(api_key="test-key", model="black-forest-labs/flux-schnell")
        create_resp = _prediction_response(201, {
            "status": "failed", "error": "NSFW content detected", "urls": {"get": "https://x/get"},
        })
        with patch("docu_studio.adapters.image_gen.replicate_adapter.requests.post", return_value=create_resp), \
             patch("time.sleep"), \
             pytest.raises(RuntimeError, match="NSFW content detected"):
            adapter.generate("prompt", 1080, 1920)

    def test_landscape_dimensions_request_16_9(self) -> None:
        adapter = ReplicateImageGenAdapter(api_key="test-key", model="black-forest-labs/flux-schnell")
        create_resp = _prediction_response(201, {
            "status": "succeeded", "output": ["https://x/out.png"], "urls": {"get": "https://x/get"},
        })
        with patch("docu_studio.adapters.image_gen.replicate_adapter.requests.post", return_value=create_resp) as mock_post, \
             patch("docu_studio.adapters.image_gen.replicate_adapter.requests.get", return_value=_image_download_response()):
            adapter.generate("prompt", 1920, 1080)
        assert mock_post.call_args.kwargs["json"]["input"]["aspect_ratio"] == "16:9"


class TestRetryBehavior:
    def test_retries_on_create_call_failure_then_succeeds(self) -> None:
        adapter = ReplicateImageGenAdapter(api_key="test-key", model="black-forest-labs/flux-schnell")
        create_resp = _prediction_response(201, {
            "status": "succeeded", "output": ["https://x/out.png"], "urls": {"get": "https://x/get"},
        })
        with patch(
            "docu_studio.adapters.image_gen.replicate_adapter.requests.post",
            side_effect=[RuntimeError("connection reset"), create_resp],
        ), patch("docu_studio.adapters.image_gen.replicate_adapter.requests.get", return_value=_image_download_response()), \
           patch("time.sleep"):
            result = adapter.generate("prompt", 1080, 1920)
        assert result == _FAKE_PNG_BYTES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_replicate_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `ReplicateImageGenAdapter`**

Create `docu_studio/adapters/image_gen/replicate_adapter.py`:

```python
"""Replicate image generation adapter — hosts FLUX (Black Forest Labs), SDXL
(Stability AI), and other models behind one HTTP API. Prediction creation is
asynchronous: POST to create, then poll the returned status URL until the
prediction reaches a terminal state, then download the output URL."""
from __future__ import annotations

import time

import requests

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

_PREDICTIONS_URL_TEMPLATE = "https://api.replicate.com/v1/models/{model}/predictions"
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 120.0
_TERMINAL_STATUSES = ("succeeded", "failed", "canceled")


def _aspect_ratio(width: int, height: int) -> str:
    if width == height:
        return "1:1"
    return "9:16" if height > width else "16:9"


class ReplicateImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = requests.post(
            _PREDICTIONS_URL_TEMPLATE.format(model=self._model),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Prefer": "wait=30",
            },
            json={"input": {"prompt": prompt, "aspect_ratio": _aspect_ratio(width, height)}},
            timeout=45,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Replicate prediction create failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        prediction = self._await_completion(response.json())
        return self._download_output(prediction)

    def _await_completion(self, prediction: dict) -> dict:
        elapsed = 0.0
        while prediction.get("status") not in _TERMINAL_STATUSES:
            if elapsed >= _POLL_TIMEOUT_SECONDS:
                raise RuntimeError("Replicate prediction timed out")
            time.sleep(_POLL_INTERVAL_SECONDS)
            elapsed += _POLL_INTERVAL_SECONDS
            poll_response = requests.get(
                prediction["urls"]["get"],
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=30,
            )
            poll_response.raise_for_status()
            prediction = poll_response.json()
        if prediction.get("status") != "succeeded":
            raise RuntimeError(f"Replicate prediction failed: {prediction.get('error')}")
        return prediction

    def _download_output(self, prediction: dict) -> bytes:
        output = prediction.get("output")
        url = output[0] if isinstance(output, list) else output
        if not url:
            raise RuntimeError("Replicate prediction succeeded but returned no output")
        image_response = requests.get(url, timeout=30)
        image_response.raise_for_status()
        return image_response.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_replicate_adapter.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/adapters/image_gen/replicate_adapter.py tests/unit/test_image_gen_replicate_adapter.py
git commit -m "feat(image-gen): add Replicate adapter (FLUX, SDXL)"
```

---

### Task 5: fal.ai adapter (FLUX)

**Files:**
- Create: `docu_studio/adapters/image_gen/fal_adapter.py`
- Test: `tests/unit/test_image_gen_fal_adapter.py`

**Interfaces:**
- Consumes: `ImageGenProvider` (Task 2).
- Produces: `FalImageGenAdapter(api_key: str, model: str)` — `model` is a model
  path like `"fal-ai/flux/schnell"`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_image_gen_fal_adapter.py`:

```python
"""Unit tests for FalImageGenAdapter. requests.post is mocked throughout; no
real network calls happen. fal.ai's queue.fal.run endpoint returns the result
directly in the initial response for fast models (schnell-tier) — this
adapter reads the synchronous response shape."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from docu_studio.adapters.image_gen.fal_adapter import FalImageGenAdapter

_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake image bytes"


def _success_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "images": [
            {"url": "https://fal.media/files/out.png", "width": 1080, "height": 1920, "content_type": "image/png"}
        ]
    }
    return resp


def _image_download_response() -> MagicMock:
    resp = MagicMock()
    resp.content = _FAKE_PNG_BYTES
    resp.raise_for_status = MagicMock()
    return resp


class TestGenerate:
    def test_returns_downloaded_bytes(self) -> None:
        adapter = FalImageGenAdapter(api_key="test-key", model="fal-ai/flux/schnell")
        with patch("docu_studio.adapters.image_gen.fal_adapter.requests.post", return_value=_success_response()), \
             patch("docu_studio.adapters.image_gen.fal_adapter.requests.get", return_value=_image_download_response()):
            result = adapter.generate("a red bicycle", 1080, 1920)
        assert result == _FAKE_PNG_BYTES

    def test_posts_to_model_endpoint_with_key_auth_header(self) -> None:
        adapter = FalImageGenAdapter(api_key="test-key", model="fal-ai/flux/schnell")
        with patch("docu_studio.adapters.image_gen.fal_adapter.requests.post", return_value=_success_response()) as mock_post, \
             patch("docu_studio.adapters.image_gen.fal_adapter.requests.get", return_value=_image_download_response()):
            adapter.generate("a red bicycle", 1080, 1920)
        args, kwargs = mock_post.call_args
        assert args[0] == "https://queue.fal.run/fal-ai/flux/schnell"
        assert kwargs["headers"]["Authorization"] == "Key test-key"
        assert kwargs["json"]["prompt"] == "a red bicycle"
        assert kwargs["json"]["image_size"] == {"width": 1080, "height": 1920}

    def test_raises_on_non_200_status(self) -> None:
        adapter = FalImageGenAdapter(api_key="test-key", model="fal-ai/flux/schnell")
        resp = MagicMock(status_code=422, text="invalid input")
        with patch("docu_studio.adapters.image_gen.fal_adapter.requests.post", return_value=resp), \
             patch("time.sleep"), \
             pytest.raises(RuntimeError, match="422"):
            adapter.generate("prompt", 1080, 1920)

    def test_raises_when_no_images_in_response(self) -> None:
        adapter = FalImageGenAdapter(api_key="test-key", model="fal-ai/flux/schnell")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"images": []}
        with patch("docu_studio.adapters.image_gen.fal_adapter.requests.post", return_value=resp), \
             patch("time.sleep"), \
             pytest.raises(RuntimeError, match="no image"):
            adapter.generate("prompt", 1080, 1920)


class TestRetryBehavior:
    def test_retries_on_connection_error_then_succeeds(self) -> None:
        adapter = FalImageGenAdapter(api_key="test-key", model="fal-ai/flux/schnell")
        with patch(
            "docu_studio.adapters.image_gen.fal_adapter.requests.post",
            side_effect=[requests.exceptions.ConnectionError("reset"), _success_response()],
        ), patch("docu_studio.adapters.image_gen.fal_adapter.requests.get", return_value=_image_download_response()), \
           patch("time.sleep"):
            result = adapter.generate("prompt", 1080, 1920)
        assert result == _FAKE_PNG_BYTES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_fal_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `FalImageGenAdapter`**

Create `docu_studio/adapters/image_gen/fal_adapter.py`:

```python
"""fal.ai image generation adapter — hosts FLUX and other models behind
queue.fal.run. Fast (schnell-tier) models return their result directly in the
initial response rather than requiring polling, which this adapter relies on."""
from __future__ import annotations

import requests

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

_QUEUE_URL_TEMPLATE = "https://queue.fal.run/{model}"


class FalImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = requests.post(
            _QUEUE_URL_TEMPLATE.format(model=self._model),
            headers={
                "Authorization": f"Key {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"prompt": prompt, "image_size": {"width": width, "height": height}},
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"fal.ai image generation failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        images = response.json().get("images", [])
        if not images:
            raise RuntimeError("fal.ai image generation returned no image")
        image_response = requests.get(images[0]["url"], timeout=30)
        image_response.raise_for_status()
        return image_response.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_fal_adapter.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/adapters/image_gen/fal_adapter.py tests/unit/test_image_gen_fal_adapter.py
git commit -m "feat(image-gen): add fal.ai adapter (FLUX)"
```

---

### Task 6: Preset factory

**Files:**
- Create: `docu_studio/adapters/image_gen/factory.py`
- Test: `tests/unit/test_image_gen_factory.py`

**Interfaces:**
- Consumes: `OpenAIImageGenAdapter`, `GeminiImageGenAdapter`,
  `ReplicateImageGenAdapter`, `FalImageGenAdapter` (Tasks 2-5).
- Produces: `IMAGE_GEN_PRESETS: dict[str, dict]` (preset id → `{provider, model,
  price_per_image_usd, label}`) — consumed by `shorts_config.py` (Task 7, for
  validation) and by `bridge.py` (Task 11, for provider construction).
  `build_image_gen_provider(preset_id: str, openai_key: str, gemini_key: str,
  replicate_key: str, fal_key: str) -> ImageGenProvider`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_image_gen_factory.py`:

```python
"""Unit tests for docu_studio.adapters.image_gen.factory."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from docu_studio.adapters.image_gen.factory import (
    IMAGE_GEN_PRESETS,
    build_image_gen_provider,
)


class TestImageGenPresets:
    def test_covers_all_four_providers(self) -> None:
        providers = {preset["provider"] for preset in IMAGE_GEN_PRESETS.values()}
        assert providers == {"openai", "gemini", "replicate", "fal"}

    def test_every_preset_has_a_positive_price(self) -> None:
        for preset_id, preset in IMAGE_GEN_PRESETS.items():
            assert preset["price_per_image_usd"] > 0, preset_id

    def test_every_preset_has_a_label(self) -> None:
        for preset_id, preset in IMAGE_GEN_PRESETS.items():
            assert preset["label"], preset_id


class TestBuildImageGenProvider:
    def test_openai_preset_builds_openai_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.openai_adapter.OpenAIImageGenAdapter") as mock_cls:
            build_image_gen_provider("openai_gpt_image_1", "openai-key", "", "", "")
        mock_cls.assert_called_once_with(api_key="openai-key", model="gpt-image-1")

    def test_gemini_preset_builds_gemini_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.gemini_adapter.GeminiImageGenAdapter") as mock_cls:
            build_image_gen_provider("gemini_nano_banana_pro", "", "gemini-key", "", "")
        mock_cls.assert_called_once_with(api_key="gemini-key", model="gemini-3-pro-image-preview")

    def test_replicate_preset_builds_replicate_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.replicate_adapter.ReplicateImageGenAdapter") as mock_cls:
            build_image_gen_provider("replicate_flux_schnell", "", "", "replicate-key", "")
        mock_cls.assert_called_once_with(api_key="replicate-key", model="black-forest-labs/flux-schnell")

    def test_fal_preset_builds_fal_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.fal_adapter.FalImageGenAdapter") as mock_cls:
            build_image_gen_provider("fal_flux_dev", "", "", "", "fal-key")
        mock_cls.assert_called_once_with(api_key="fal-key", model="fal-ai/flux/dev")

    def test_unknown_preset_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown image-gen preset"):
            build_image_gen_provider("not_a_real_preset", "", "", "", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_factory.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the factory**

Create `docu_studio/adapters/image_gen/factory.py`:

```python
"""Curated model presets + factory for image-generation adapters. Prices are
static, published-price estimates captured at spec time — used only for the
GUI's pre-run cost estimate, not for billing. Update manually if a vendor
changes pricing."""
from __future__ import annotations

import logging

from docu_studio.adapters.image_gen.base import ImageGenProvider

_log = logging.getLogger(__name__)

IMAGE_GEN_PRESETS: dict[str, dict] = {
    "openai_gpt_image_1": {
        "provider": "openai", "model": "gpt-image-1",
        "price_per_image_usd": 0.07,
        "label": "OpenAI — GPT-Image-1 (premium, ~$0.07/image)",
    },
    "gemini_nano_banana": {
        "provider": "gemini", "model": "gemini-2.5-flash-image",
        "price_per_image_usd": 0.04,
        "label": "Google — Nano Banana (mid, ~$0.04/image)",
    },
    "gemini_nano_banana_pro": {
        "provider": "gemini", "model": "gemini-3-pro-image-preview",
        "price_per_image_usd": 0.15,
        "label": "Google — Nano Banana Pro (premium, ~$0.15/image)",
    },
    "replicate_flux_schnell": {
        "provider": "replicate", "model": "black-forest-labs/flux-schnell",
        "price_per_image_usd": 0.003,
        "label": "Replicate — FLUX.1 Schnell (cheap, ~$0.003/image)",
    },
    "replicate_flux_dev": {
        "provider": "replicate", "model": "black-forest-labs/flux-dev",
        "price_per_image_usd": 0.025,
        "label": "Replicate — FLUX.1 Dev (mid, ~$0.025/image)",
    },
    "replicate_sdxl": {
        "provider": "replicate", "model": "stability-ai/sdxl",
        "price_per_image_usd": 0.0055,
        "label": "Replicate — SDXL (cheap, ~$0.0055/image)",
    },
    "fal_flux_schnell": {
        "provider": "fal", "model": "fal-ai/flux/schnell",
        "price_per_image_usd": 0.003,
        "label": "fal.ai — FLUX.1 Schnell (cheap, ~$0.003/image)",
    },
    "fal_flux_dev": {
        "provider": "fal", "model": "fal-ai/flux/dev",
        "price_per_image_usd": 0.025,
        "label": "fal.ai — FLUX.1 Dev (mid, ~$0.025/image)",
    },
}


def build_image_gen_provider(
    preset_id: str, openai_key: str, gemini_key: str, replicate_key: str, fal_key: str,
) -> ImageGenProvider:
    preset = IMAGE_GEN_PRESETS.get(preset_id)
    if preset is None:
        raise ValueError(f"Unknown image-gen preset {preset_id!r}")
    provider, model = preset["provider"], preset["model"]

    if provider == "openai":
        from docu_studio.adapters.image_gen.openai_adapter import OpenAIImageGenAdapter
        return OpenAIImageGenAdapter(api_key=openai_key, model=model)
    if provider == "gemini":
        from docu_studio.adapters.image_gen.gemini_adapter import GeminiImageGenAdapter
        return GeminiImageGenAdapter(api_key=gemini_key, model=model)
    if provider == "replicate":
        from docu_studio.adapters.image_gen.replicate_adapter import ReplicateImageGenAdapter
        return ReplicateImageGenAdapter(api_key=replicate_key, model=model)
    from docu_studio.adapters.image_gen.fal_adapter import FalImageGenAdapter
    return FalImageGenAdapter(api_key=fal_key, model=model)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_image_gen_factory.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/adapters/image_gen/factory.py tests/unit/test_image_gen_factory.py
git commit -m "feat(image-gen): add preset table and provider factory"
```

---

### Task 7: `ShortsConfig` — `ai_image` footage source + model/continuity fields

**Files:**
- Modify: `docu_studio/shorts/shorts_config.py`
- Test: `tests/unit/test_shorts_config.py`

**Interfaces:**
- Consumes: `IMAGE_GEN_PRESETS` (Task 6).
- Produces: `SHORTS_FOOTAGE_SOURCES` gains `"ai_image"`; `ShortsConfig.ai_image_model:
  str` and `ShortsConfig.ai_story_continuity: bool` — consumed by
  `shorts_runner.py` (Task 10).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_shorts_config.py` (import block gains
`SHORTS_DEFAULT_AI_IMAGE_MODEL`; append a new test class after
`TestShortsFootageSource`):

```python
from docu_studio.shorts.shorts_config import (
    SHORTS_ASPECT_DIMENSIONS,
    SHORTS_DEFAULT_AI_IMAGE_MODEL,
    SHORTS_DEFAULT_ASPECT,
    SHORTS_DEFAULT_DURATION,
    SHORTS_DEFAULT_FOOTAGE_SOURCE,
    SHORTS_DEFAULT_MUSIC_VOLUME_DB,
    SHORTS_FOOTAGE_SOURCES,
    SHORTS_HEIGHT,
    SHORTS_MAX_DURATION,
    SHORTS_MIN_DURATION,
    SHORTS_MUSIC_VOLUME_MAX_DB,
    SHORTS_MUSIC_VOLUME_MIN_DB,
    SHORTS_WIDTH,
    ShortsConfig,
)
```

```python
class TestShortsAiImageSource:
    def test_ai_image_is_a_known_footage_source(self) -> None:
        assert "ai_image" in SHORTS_FOOTAGE_SOURCES

    def test_accepts_ai_image_footage_source(self) -> None:
        cfg = ShortsConfig(topic="x", footage_source="ai_image")
        assert cfg.footage_source == "ai_image"

    def test_ai_image_model_defaults_to_a_known_preset(self) -> None:
        from docu_studio.adapters.image_gen.factory import IMAGE_GEN_PRESETS
        cfg = ShortsConfig(topic="x")
        assert cfg.ai_image_model == SHORTS_DEFAULT_AI_IMAGE_MODEL
        assert cfg.ai_image_model in IMAGE_GEN_PRESETS

    def test_accepts_any_known_preset(self) -> None:
        ShortsConfig(topic="x", footage_source="ai_image", ai_image_model="fal_flux_schnell")

    def test_rejects_unknown_preset(self) -> None:
        with pytest.raises(ValueError, match="ai_image_model"):
            ShortsConfig(topic="x", footage_source="ai_image", ai_image_model="not_a_real_preset")

    def test_story_continuity_defaults_to_true(self) -> None:
        cfg = ShortsConfig(topic="x")
        assert cfg.ai_story_continuity is True

    def test_story_continuity_can_be_disabled(self) -> None:
        cfg = ShortsConfig(topic="x", ai_story_continuity=False)
        assert cfg.ai_story_continuity is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'SHORTS_DEFAULT_AI_IMAGE_MODEL'`

- [ ] **Step 3: Implement the config changes**

In `docu_studio/shorts/shorts_config.py`, add the import and constants, extend
`SHORTS_FOOTAGE_SOURCES`, add the two new fields, and validate:

```python
from docu_studio.adapters.image_gen.factory import IMAGE_GEN_PRESETS
from docu_studio.common.captions import CAPTION_STYLES, DEFAULT_CAPTION_STYLE
```

```python
SHORTS_FOOTAGE_SOURCES = ("video", "image", "ai_image")
SHORTS_DEFAULT_FOOTAGE_SOURCE = "video"
SHORTS_DEFAULT_AI_IMAGE_MODEL = "replicate_flux_schnell"
```

In `ShortsConfig`, add the two fields (after `footage_source`):

```python
    ai_image_model: str = SHORTS_DEFAULT_AI_IMAGE_MODEL
    ai_story_continuity: bool = True
```

In `__post_init__`, add validation right after the existing `footage_source` check:

```python
        if self.ai_image_model not in IMAGE_GEN_PRESETS:
            raise ValueError(
                f"ai_image_model must be one of {sorted(IMAGE_GEN_PRESETS)}, "
                f"got {self.ai_image_model!r}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_config.py -v`
Expected: PASS (all tests, including the 7 new ones)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/shorts_config.py tests/unit/test_shorts_config.py
git commit -m "feat(shorts): add ai_image footage source, model preset, and story-continuity config"
```

---

### Task 8: `shorts_script_gen.py` — style guide + detailed per-scene AI image prompts

**Files:**
- Modify: `docu_studio/shorts/shorts_script_gen.py`
- Test: `tests/unit/test_shorts_script_gen.py`

**Interfaces:**
- Produces: `ShortsScript.image_prompts: tuple[str, ...] = ()`.
  `generate_shorts_script(..., footage_source: str = "video", story_continuity:
  bool = True)` — consumed by `shorts_runner.py` (Task 10).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_shorts_script_gen.py` (new test classes at the end of
the file, after the existing `TestGenerateShortsScript` class):

```python
class TestGenerateShortsScriptAiImageIndependent:
    def test_populates_image_prompts_aligned_to_sentences(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger."
        llm.break_into_scenes.return_value = [
            {
                "title": "aerial city night", "narration": "Fact one is huge.",
                "image_prompt": "Wide establishing shot of a glittering city skyline at night, cinematic lighting.",
                "music_moods": ["epic", "cinematic", "dramatic"],
            },
            {
                "title": "close-up hands typing", "narration": "Fact two is bigger.",
                "image_prompt": "Close-up of hands typing rapidly on a mechanical keyboard, warm desk lamp light.",
            },
        ]

        result = generate_shorts_script(
            "Cities at night", 30, llm, footage_source="ai_image", story_continuity=False,
        )

        assert len(result.image_prompts) == 2
        assert "glittering city skyline" in result.image_prompts[0]
        assert "hands typing" in result.image_prompts[1]
        # visual_queries (stock fallback) still populated regardless of mode:
        assert result.visual_queries == ["aerial city night", "close-up hands typing"]

    def test_does_not_call_style_guide_generation_when_independent(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        llm.break_into_scenes.return_value = [
            {"title": "a", "narration": "One sentence.", "image_prompt": "prompt one"},
            {"title": "b", "narration": "Two sentence.", "image_prompt": "prompt two"},
        ]

        generate_shorts_script("Topic", 30, llm, footage_source="ai_image", story_continuity=False)

        # generate_script called exactly once (for the main narration only —
        # no extra style-guide call):
        assert llm.generate_script.call_count == 1

    def test_video_mode_leaves_image_prompts_empty(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        llm.break_into_scenes.return_value = [
            {"title": "a", "narration": "One sentence."},
            {"title": "b", "narration": "Two sentence."},
        ]

        result = generate_shorts_script("Topic", 30, llm, footage_source="video")

        assert result.image_prompts == ()


class TestGenerateShortsScriptAiImageStoryContinuity:
    def test_style_guide_call_happens_before_per_sentence_call(self) -> None:
        llm = MagicMock()
        llm.generate_script.side_effect = [
            "Fact one is huge. Fact two is bigger.",  # main narration call
            "Cinematic photography style, warm palette. A lone astronaut in a weathered white suit.",  # style-guide call
        ]
        llm.break_into_scenes.return_value = [
            {
                "title": "astronaut walking", "narration": "Fact one is huge.",
                "image_prompt": "Cinematic photography, warm palette, lone astronaut in weathered white suit walking on dunes.",
                "music_moods": ["epic", "cinematic", "dramatic"],
            },
            {
                "title": "astronaut looking up", "narration": "Fact two is bigger.",
                "image_prompt": "Cinematic photography, warm palette, same astronaut looking up at a huge red planet.",
            },
        ]

        result = generate_shorts_script(
            "A lone astronaut", 30, llm, footage_source="ai_image", story_continuity=True,
        )

        assert llm.generate_script.call_count == 2
        assert len(result.image_prompts) == 2
        assert "astronaut" in result.image_prompts[0]
        assert "astronaut" in result.image_prompts[1]

    def test_style_guide_failure_falls_back_to_independent_prompts(self) -> None:
        llm = MagicMock()
        llm.generate_script.side_effect = [
            "One sentence. Two sentence.",
            RuntimeError("style guide call failed"),
        ]
        llm.break_into_scenes.return_value = [
            {"title": "a", "narration": "One sentence.", "image_prompt": "prompt one"},
            {"title": "b", "narration": "Two sentence.", "image_prompt": "prompt two"},
        ]

        result = generate_shorts_script(
            "Topic", 30, llm, footage_source="ai_image", story_continuity=True,
        )

        assert len(result.image_prompts) == 2

    def test_image_prompt_extraction_failure_falls_back_to_visual_queries(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        # Both scene-extraction attempts are missing image_prompt entirely:
        llm.break_into_scenes.return_value = [
            {"title": "query one", "narration": "One sentence."},
            {"title": "query two", "narration": "Two sentence."},
        ]

        result = generate_shorts_script(
            "Topic", 30, llm, footage_source="ai_image", story_continuity=False,
        )

        assert result.image_prompts == ("query one", "query two")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_script_gen.py -v`
Expected: FAIL — `TypeError: generate_shorts_script() got an unexpected keyword
argument 'footage_source'`

- [ ] **Step 3: Implement the script-gen changes**

In `docu_studio/shorts/shorts_script_gen.py`, add the new templates after
`_QUERY_OVERRIDE_TEMPLATE`:

```python
_STYLE_GUIDE_TEMPLATE = (
    "Here is a video narration script:\n\n{script}\n\n"
    "---\n"
    "Write a short VISUAL STYLE GUIDE (120-180 words) for illustrating this script as a "
    "sequence of AI-generated images that must look like one consistent, cohesive story. "
    "Cover, in prose:\n"
    "1. Art style/medium (e.g. cinematic photography, watercolor illustration, 3D render) "
    "and overall color palette/mood.\n"
    "2. The main recurring subject(s) — if the script follows a person, character, place, "
    "or object across multiple scenes, describe their fixed appearance in specific, concrete "
    "visual terms (age, build, clothing, materials, colors) so it can be repeated identically "
    "in every scene. If the script has no single recurring subject (e.g. it covers many "
    "different facts/places), say so explicitly instead of inventing one.\n"
    "3. The recurring setting/era/environment, if any.\n\n"
    "Write only the style guide text — nothing else, no headers, no markdown."
)

_QUERY_OVERRIDE_TEMPLATE_AI_IMAGE = (
    "{script}\n\n"
    "---\n"
    "IGNORE the 'logical scenes' framing in the instructions above. Instead, split "
    "the script above into its individual sentences, in the exact order they appear, "
    "with no merging, omission, or paraphrasing. For each sentence:\n"
    "- 'narration' must be the sentence exactly as written above.\n"
    "- 'title' must be a concrete 2-5 word visual search query describing stock "
    "footage that would visually match that sentence (e.g. 'aerial city night', "
    "'close-up hands typing'). No abstract or vague terms.\n"
    "- 'image_prompt' must be a detailed, concrete prompt (40-80 words) for an AI "
    "image-generation model to illustrate that exact sentence: specify the subject, "
    "specific action/pose, setting, camera framing/shot type (e.g. wide establishing "
    "shot, close-up, over-the-shoulder), lighting, and mood. Be precise and visual, "
    "not abstract — describe exactly what should be seen in frame.\n"
    "Additionally, on the FIRST entry only, include a 'music_moods' key: an array "
    "of exactly 3 different single-word background-music mood/genre tags for this "
    "whole video, ordered from most fitting to least fitting (e.g. [\"epic\", "
    "\"cinematic\", \"dramatic\"]). Each word should be a term commonly used to tag "
    "instrumental background music. Omit this key on every other entry.\n"
    "Return one entry per sentence, in order."
)

_QUERY_OVERRIDE_TEMPLATE_AI_IMAGE_STORY = (
    "{script}\n\n"
    "---\n"
    "VISUAL STYLE GUIDE for this video (every image must follow this consistently):\n"
    "{style_guide}\n"
    "---\n"
    "IGNORE the 'logical scenes' framing in the instructions above. Instead, split "
    "the script above into its individual sentences, in the exact order they appear, "
    "with no merging, omission, or paraphrasing. For each sentence:\n"
    "- 'narration' must be the sentence exactly as written above.\n"
    "- 'title' must be a concrete 2-5 word visual search query describing stock "
    "footage that would visually match that sentence (e.g. 'aerial city night', "
    "'close-up hands typing'). No abstract or vague terms.\n"
    "- 'image_prompt' must be a detailed, concrete prompt (50-100 words) for an AI "
    "image-generation model to illustrate that exact sentence, and MUST open by "
    "restating the style guide's art style and recurring subject/setting description "
    "above (in your own words, consistently across every entry), then add this "
    "sentence's specific action, camera framing/shot type, lighting, and mood. Be "
    "precise and visual, not abstract.\n"
    "Additionally, on the FIRST entry only, include a 'music_moods' key: an array "
    "of exactly 3 different single-word background-music mood/genre tags for this "
    "whole video, ordered from most fitting to least fitting (e.g. [\"epic\", "
    "\"cinematic\", \"dramatic\"]). Each word should be a term commonly used to tag "
    "instrumental background music. Omit this key on every other entry.\n"
    "Return one entry per sentence, in order."
)
```

Update `ShortsScript` to add the new field:

```python
@dataclass(frozen=True)
class ShortsScript:
    text: str
    sentences: list[str]
    visual_queries: list[str]
    music_moods: tuple[str, ...] = (DEFAULT_MUSIC_MOOD,)
    image_prompts: tuple[str, ...] = ()
```

Replace `_fetch_scene_json` to take an already-formatted prompt (was: raw script
text + hardcoded template internally):

```python
def _fetch_scene_json(llm: LLMProvider, prompt: str) -> list[dict] | None:
    """Make the single break_into_scenes call shared by query/mood/image-prompt
    extraction. *prompt* is the already-formatted instruction string (the
    query, AI-image, or AI-image-story template applied to the script)."""
    try:
        raw = llm.break_into_scenes(prompt)
    except Exception as exc:
        _log.warning("Shorts visual-query extraction call failed: %s", exc)
        return None
    return raw if isinstance(raw, list) else None
```

Add the style-guide generator and the image-prompt parser, right after
`_moods_from_raw`:

```python
def _generate_style_guide(llm: LLMProvider, script_text: str) -> str:
    """One-shot call producing a reusable visual style/character/setting
    description, folded into every per-sentence image_prompt so AI-generated
    scenes read as one consistent story rather than disconnected images.
    Returns "" on failure — caller degrades to independent per-sentence
    prompts rather than failing the whole run over an optional call."""
    prompt = _STYLE_GUIDE_TEMPLATE.format(script=script_text)
    try:
        return llm.generate_script(topic=prompt, target_words=150).strip()
    except Exception as exc:
        _log.warning("Shorts style-guide generation failed: %s", exc)
        return ""


def _image_prompts_from_raw(raw: list[dict] | None, sentence_count: int) -> list[str] | None:
    """Parse the per-sentence AI image_prompt out of an already-fetched *raw*
    response. Returns a list aligned to *sentence_count*, or None if it
    couldn't be parsed into exactly that many non-empty entries."""
    if raw is None:
        return None
    prompts = [str(item.get("image_prompt", "")).strip() for item in raw if isinstance(item, dict)]
    prompts = [p for p in prompts if p]
    if len(prompts) != sentence_count:
        _log.warning(
            "Shorts image-prompt extraction count mismatch: got %d, expected %d",
            len(prompts), sentence_count,
        )
        return None
    return prompts
```

Replace `generate_shorts_script`'s body (signature and the scene-extraction
section) with:

```python
def generate_shorts_script(
    topic: str,
    duration_seconds: int,
    llm: LLMProvider,
    tts_provider: str = "",
    tts_voice: str = "",
    footage_source: str = "video",
    story_continuity: bool = True,
) -> ShortsScript:
    """Generate a TTS-safe shorts script and per-sentence visual queries for *topic*.

    Word target uses the stored calibration WPM for *tts_provider*+*tts_voice*
    when one exists (see docu_studio.common.tts_calibration), falling back to the 170 WPM
    default — the configured TTS voice may speak markedly slower/faster than
    that default, and using its measured pace keeps the synthesized audio
    close to *duration_seconds*.

    When *footage_source* is "ai_image", each sentence also gets a detailed
    'image_prompt' for AI image generation (ShortsScript.image_prompts). If
    *story_continuity* is also True, one extra LLM call first produces a
    reusable visual style guide (art style, recurring subject/setting) that's
    folded into every image_prompt so generated scenes read as one coherent
    story; if False, each image_prompt is generated independently per
    sentence with no shared style guide. For any other footage_source,
    image_prompts stays empty and behavior is unchanged from before.
    """
    wpm = get_wpm(tts_provider, tts_voice, default=SHORTS_WPM)
    target_words = target_word_count(duration_seconds, wpm=wpm)
    _log.info(
        "Shorts word target: %d words for %ds at %.1f WPM (provider=%s voice=%s)",
        target_words, duration_seconds, wpm, tts_provider or "?", tts_voice or "?",
    )
    prompt = _SCRIPT_INSTRUCTIONS_TEMPLATE.format(
        topic=topic, target_words=target_words,
        target_words_max=int(target_words * _OVERSHOOT_TRIM_THRESHOLD),
    )
    text = llm.generate_script(topic=prompt, target_words=target_words).strip()

    actual_words = len(text.split())
    if actual_words > target_words * _OVERSHOOT_TRIM_THRESHOLD:
        trimmed = _trim_to_word_budget(text, target_words)
        _log.warning(
            "Shorts script overshot word target (%d words for a %d-word target, "
            "%.0f%%) — trimmed to %d words to keep video duration close to requested.",
            actual_words, target_words, 100 * actual_words / target_words,
            len(trimmed.split()),
        )
        text = trimmed

    sentences = split_sentences(text)
    if not sentences:
        return ShortsScript(text=text, sentences=[], visual_queries=[])

    ai_image_mode = footage_source == "ai_image"
    style_guide = _generate_style_guide(llm, text) if (ai_image_mode and story_continuity) else ""

    def _scene_prompt() -> str:
        if not ai_image_mode:
            return _QUERY_OVERRIDE_TEMPLATE.format(script=text)
        if style_guide:
            return _QUERY_OVERRIDE_TEMPLATE_AI_IMAGE_STORY.format(script=text, style_guide=style_guide)
        return _QUERY_OVERRIDE_TEMPLATE_AI_IMAGE.format(script=text)

    raw = _fetch_scene_json(llm, _scene_prompt())
    queries = _queries_from_raw(raw, len(sentences))
    music_moods = _moods_from_raw(raw)
    image_prompts = _image_prompts_from_raw(raw, len(sentences)) if ai_image_mode else None
    if queries is None or (ai_image_mode and image_prompts is None):
        _log.info("Shorts visual-query extraction failed, retrying once")
        raw = _fetch_scene_json(llm, _scene_prompt())
        queries = _queries_from_raw(raw, len(sentences))
        if music_moods == (DEFAULT_MUSIC_MOOD,):
            music_moods = _moods_from_raw(raw)
        if ai_image_mode:
            image_prompts = _image_prompts_from_raw(raw, len(sentences))
    if queries is None:
        _log.warning(
            "Shorts visual-query extraction failed twice, falling back to topic-level query"
        )
        queries = _fallback_queries(topic, len(sentences))
    if ai_image_mode and image_prompts is None:
        _log.warning(
            "Shorts AI image-prompt extraction failed twice, falling back to visual queries as prompts"
        )
        image_prompts = list(queries)

    return ShortsScript(
        text=text, sentences=sentences, visual_queries=queries,
        music_moods=music_moods,
        image_prompts=tuple(image_prompts) if ai_image_mode else (),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_script_gen.py -v`
Expected: PASS (all existing tests + 7 new ones, zero regressions)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/shorts_script_gen.py tests/unit/test_shorts_script_gen.py
git commit -m "feat(shorts): generate detailed per-scene AI image prompts with optional style-guide continuity"
```

---

### Task 9: `shorts_assembly.py` — AI-image collection with stock-photo fallback

**Files:**
- Modify: `docu_studio/shorts/shorts_assembly.py`
- Test: `tests/unit/test_shorts_assembly.py`

**Interfaces:**
- Consumes: `ImageGenProvider.generate(prompt, width, height) -> bytes` (Task 2),
  `ShortsScript.image_prompts` (Task 8).
- Produces: `_collect_ai_images_per_sentence(script, image_gen_provider,
  photo_providers, scene_dir, output_dimensions, event_queue) ->
  tuple[list[list[dict]], list[dict]]`. `assemble_short(...)` gains
  `image_gen_provider: ImageGenProvider | None = None` — consumed by
  `shorts_runner.py` (Task 10).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_shorts_assembly.py` — first extend the imports. The
existing top-of-file import block is:

```python
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.footage.base import FootageClip
from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.shorts.shorts_assembly import (
    SPEED_RAMP_FACTOR,
    _build_segment,
    _collect_clips,
    _collect_clips_per_sentence,
    _collect_images_per_sentence,
    _search_dedup,
)
from docu_studio.shorts.shorts_cuts import Segment
from docu_studio.shorts.shorts_script_gen import ShortsScript
```

It's missing `PhotoProvider` and `LogLevel`, and needs the new function added
to the `shorts_assembly` import. Change it to:

```python
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.footage.base import FootageClip
from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult
from docu_studio.pipeline.events import LogLevel
from docu_studio.shorts.shorts_assembly import (
    SPEED_RAMP_FACTOR,
    _build_segment,
    _collect_ai_images_per_sentence,
    _collect_clips,
    _collect_clips_per_sentence,
    _collect_images_per_sentence,
    _search_dedup,
)
from docu_studio.shorts.shorts_cuts import Segment
from docu_studio.shorts.shorts_script_gen import ShortsScript
```

Then append a new test class (place it near the existing
`TestCollectImagesPerSentence` class so photo-mode and AI-image-mode collection
tests sit together):

```python
class TestCollectAiImagesPerSentence:
    def _make_script(self, n: int) -> ShortsScript:
        return ShortsScript(
            text="irrelevant",
            sentences=[f"Sentence {i}." for i in range(n)],
            visual_queries=[f"stock query {i}" for i in range(n)],
            image_prompts=tuple(f"AI prompt {i}" for i in range(n)),
        )

    def test_successful_generation_produces_image_kind_entries(self, tmp_path: Path) -> None:
        script = self._make_script(2)
        provider = MagicMock(spec=ImageGenProvider)
        provider.generate.return_value = b"\x89PNG fake bytes"
        event_queue: queue.Queue = queue.Queue()

        pools, fallback = _collect_ai_images_per_sentence(
            script, provider, [], tmp_path, (1080, 1920), event_queue,
        )

        assert len(pools) == 2
        assert all(len(p) == 1 for p in pools)
        assert all(p[0]["kind"] == "image" for p in pools)
        assert provider.generate.call_count == 2
        provider.generate.assert_any_call("AI prompt 0", 1080, 1920)
        assert Path(pools[0][0]["path"]).read_bytes() == b"\x89PNG fake bytes"

    def test_generation_failure_falls_back_to_stock_photo_for_that_sentence(self, tmp_path: Path) -> None:
        script = self._make_script(2)
        provider = MagicMock(spec=ImageGenProvider)
        provider.generate.side_effect = [
            RuntimeError("content policy violation"),
            b"\x89PNG fake bytes for sentence 1",
        ]
        stock_provider = MagicMock(spec=PhotoProvider)
        stock_provider.search.return_value = [
            PhotoResult(url="https://example.com/stock0.jpg", width=1200, height=1600, photo_id="p0"),
        ]
        event_queue: queue.Queue = queue.Queue()

        with patch("docu_studio.shorts.shorts_assembly.download_resilient") as mock_download:
            mock_download.side_effect = lambda session, url, dest, last: Path(dest).write_bytes(b"stock jpg bytes")
            pools, _fallback = _collect_ai_images_per_sentence(
                script, provider, [stock_provider], tmp_path, (1080, 1920), event_queue,
            )

        assert pools[0][0]["kind"] == "image"
        assert Path(pools[0][0]["path"]).read_bytes() == b"stock jpg bytes"
        assert pools[1][0]["kind"] == "image"
        assert Path(pools[1][0]["path"]).read_bytes() == b"\x89PNG fake bytes for sentence 1"
        # search() is called once for sentence 0's per-sentence fallback and
        # again for the topic-level fallback_pool build at the end — assert
        # the per-sentence fallback call happened, not an exact call count:
        stock_provider.search.assert_any_call("stock query 0", page=1)

    def test_generation_failure_emits_warning_log_event(self, tmp_path: Path) -> None:
        script = self._make_script(1)
        provider = MagicMock(spec=ImageGenProvider)
        provider.generate.side_effect = RuntimeError("rate limited")
        stock_provider = MagicMock(spec=PhotoProvider)
        stock_provider.search.return_value = [
            PhotoResult(url="https://example.com/stock0.jpg", width=1200, height=1600, photo_id="p0"),
        ]
        event_queue: queue.Queue = queue.Queue()

        with patch("docu_studio.shorts.shorts_assembly.download_resilient") as mock_download:
            mock_download.side_effect = lambda session, url, dest, last: Path(dest).write_bytes(b"stock bytes")
            _collect_ai_images_per_sentence(
                script, provider, [stock_provider], tmp_path, (1080, 1920), event_queue,
            )

        events = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())
        warning_messages = [e.message for e in events if getattr(e, "level", None) == LogLevel.WARNING]
        assert any("AI image generation failed" in m for m in warning_messages)

    def test_both_ai_and_stock_fail_leaves_that_sentence_pool_empty(self, tmp_path: Path) -> None:
        # Two sentences so the overall function doesn't hit its own
        # both-totally-empty RuntimeError guard — sentence 0 fails
        # completely (AI and stock both fail), sentence 1 succeeds via AI,
        # isolating "one sentence's pool is empty" from "nothing anywhere".
        script = self._make_script(2)
        provider = MagicMock(spec=ImageGenProvider)
        provider.generate.side_effect = [
            RuntimeError("rate limited"),
            b"\x89PNG fake bytes for sentence 1",
        ]
        stock_provider = MagicMock(spec=PhotoProvider)
        stock_provider.search.return_value = []
        event_queue: queue.Queue = queue.Queue()

        pools, fallback = _collect_ai_images_per_sentence(
            script, provider, [stock_provider], tmp_path, (1080, 1920), event_queue,
        )

        assert pools[0] == []
        assert pools[1][0]["kind"] == "image"

    def test_fallback_pool_built_from_stock_search_not_extra_ai_generation(self, tmp_path: Path) -> None:
        script = self._make_script(1)
        provider = MagicMock(spec=ImageGenProvider)
        provider.generate.return_value = b"\x89PNG fake bytes"
        stock_provider = MagicMock(spec=PhotoProvider)
        stock_provider.search.return_value = [
            PhotoResult(url="https://example.com/fallback0.jpg", width=1200, height=1600, photo_id="f0"),
        ]
        event_queue: queue.Queue = queue.Queue()

        with patch("docu_studio.shorts.shorts_assembly.download_resilient") as mock_download:
            mock_download.side_effect = lambda session, url, dest, last: Path(dest).write_bytes(b"fallback bytes")
            _pools, fallback = _collect_ai_images_per_sentence(
                script, provider, [stock_provider], tmp_path, (1080, 1920), event_queue,
            )

        # generate() called only once (for the one sentence) — the fallback
        # pool must not trigger a second AI generation call:
        assert provider.generate.call_count == 1
        assert len(fallback) == 1
        assert fallback[0]["kind"] == "image"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_assembly.py -v -k AiImages`
Expected: FAIL — `ImportError: cannot import name '_collect_ai_images_per_sentence'`

- [ ] **Step 3: Implement `_collect_ai_images_per_sentence`**

In `docu_studio/shorts/shorts_assembly.py`, add the new import:

```python
from docu_studio.adapters.image_gen.base import ImageGenProvider
```

Add the new function right after `_collect_images_per_sentence` (before the
blank-line separator at line ~359):

```python
def _collect_ai_images_per_sentence(
    script: ShortsScript,
    image_gen_provider: ImageGenProvider,
    photo_providers: list[PhotoProvider],
    scene_dir: Path,
    output_dimensions: tuple[int, int],
    event_queue: queue.Queue,
) -> tuple[list[list[dict]], list[dict]]:
    """AI-image counterpart to _collect_images_per_sentence: generate one AI
    image per sentence from script.image_prompts[i]; on generation failure,
    fall back to a single stock-photo search using script.visual_queries[i]
    (the existing stock-photo safety-net infra), logging the fallback so the
    user can see it happened. Every successful pool entry — AI-generated or
    stock-fallback — is tagged "kind": "image" so _build_segment's existing
    image branch needs no changes. Returns (per_sentence_pools, fallback_pool)
    in the exact shape assemble_short's pool-resolution logic already expects.
    fallback_pool is built once via a stock-photo search (not a second AI
    generation) as the rare safety net for sentences where both AI generation
    and the per-sentence stock fallback failed — this avoids spending
    image-generation budget on a fallback that's usually never used.
    """
    out_width, out_height = output_dimensions
    session = build_download_session()
    last_request_at: dict[str, float] = {}
    per_sentence_pools: list[list[dict]] = []
    generated_count = 0

    for i, image_prompt in enumerate(script.image_prompts):
        dest = str(scene_dir / f"ai_img_{i:03d}.png")
        try:
            image_bytes = image_gen_provider.generate(image_prompt, out_width, out_height)
            Path(dest).write_bytes(image_bytes)
            per_sentence_pools.append(
                [{"path": dest, "width": out_width, "height": out_height, "kind": "image"}]
            )
            generated_count += 1
            _log.info("_collect_ai_images_per_sentence: sentence %d generated via AI", i)
            continue
        except Exception as exc:
            _log.warning(
                "_collect_ai_images_per_sentence: AI generation failed for sentence %d (%s) — "
                "falling back to stock photo", i, exc,
            )

        query = script.visual_queries[i]
        candidates = _search_one_photo_query(photo_providers, query, 1)
        if not candidates:
            per_sentence_pools.append([])
            event_queue.put(LogEvent(
                message=f"Sentence {i}: AI image generation failed and no stock photo "
                        "fallback was found.",
                level=LogLevel.WARNING,
            ))
            continue

        photo = candidates[0]
        ext = Path(urlparse(photo.url).path).suffix or ".jpg"
        stock_dest = str(scene_dir / f"ai_img_{i:03d}_stock{ext}")
        try:
            download_resilient(session, photo.url, stock_dest, last_request_at)
            per_sentence_pools.append(
                [{"path": stock_dest, "width": photo.width, "height": photo.height, "kind": "image"}]
            )
            event_queue.put(LogEvent(
                message=f"Sentence {i}: AI image generation failed — used a stock photo instead.",
                level=LogLevel.WARNING,
            ))
        except Exception as exc:
            _log.warning(
                "_collect_ai_images_per_sentence: stock fallback download failed for "
                "sentence %d (%s)", i, exc,
            )
            per_sentence_pools.append([])

    fallback_pool: list[dict] = []
    topic_query = script.visual_queries[0] if script.visual_queries else "documentary photo"
    fallback_candidates = _search_one_photo_query(
        photo_providers, topic_query, _MAX_CANDIDATES_PER_QUERY,
    )
    for j, photo in enumerate(fallback_candidates):
        ext = Path(urlparse(photo.url).path).suffix or ".jpg"
        dest = str(scene_dir / f"ai_img_fallback_{j:03d}{ext}")
        try:
            download_resilient(session, photo.url, dest, last_request_at)
            fallback_pool.append({"path": dest, "width": photo.width, "height": photo.height, "kind": "image"})
        except Exception as exc:
            _log.info("_collect_ai_images_per_sentence: fallback download failed for %s (%s)", photo.url, exc)

    if not any(per_sentence_pools) and not fallback_pool:
        raise RuntimeError(
            "Shorts assembly: no AI-generated or stock fallback images available for any sentence."
        )

    event_queue.put(LogEvent(
        message=f"Shorts AI images: {generated_count} of {len(script.sentences)} sentences "
                f"generated by AI (+{len(fallback_pool)} fallback).",
        level=LogLevel.INFO,
    ))
    return per_sentence_pools, fallback_pool
```

Now wire it into `assemble_short`. Modify the signature (add the new parameter
after `photo_providers`):

```python
    footage_source: str = "video",
    photo_providers: list[PhotoProvider] | None = None,
    image_gen_provider: ImageGenProvider | None = None,
) -> None:
```

Modify the footage-source branch (currently `if footage_source == "image": ...
else: ...` around line 587) to add a third arm:

```python
    if footage_source == "ai_image":
        event_queue.put(ProgressEvent(stage="Short Footage", message="Generating AI images…"))
        per_sentence_pools, fallback_pool = _collect_ai_images_per_sentence(
            script, image_gen_provider, photo_providers or [], scene_dir,
            output_dimensions, event_queue,
        )
    elif footage_source == "image":
        event_queue.put(ProgressEvent(stage="Short Footage", message="Searching stock photos…"))
        per_sentence_pools, fallback_pool = _collect_images_per_sentence(
            script, photo_providers or [], scene_dir, event_queue,
        )
    else:
        event_queue.put(ProgressEvent(stage="Short Footage", message="Searching stock footage…"))
        per_sentence_pools, fallback_pool = _collect_clips_per_sentence(script, providers, scene_dir, event_queue)
```

No changes to `_build_segment()` — its existing `kind == "image"` branch already
handles every pool entry this function produces.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_shorts_assembly.py -v`
Expected: PASS (all existing tests + 5 new ones, zero regressions — in
particular the existing `TestBuildSegmentImageBranch` tests must still pass
unchanged, confirming `_build_segment` needed no edits)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/shorts_assembly.py tests/unit/test_shorts_assembly.py
git commit -m "feat(shorts): collect AI-generated per-sentence images with stock-photo fallback"
```

---

### Task 10: `ShortsRunner` wiring

**Files:**
- Modify: `docu_studio/shorts/shorts_runner.py`

**Interfaces:**
- Consumes: `ImageGenProvider` (Task 2), `ShortsConfig.ai_image_model` /
  `ai_story_continuity` (Task 7), `generate_shorts_script(...,
  footage_source=..., story_continuity=...)` (Task 8), `assemble_short(...,
  image_gen_provider=...)` (Task 9).
- Produces: `ShortsRunner(..., image_gen_provider: ImageGenProvider | None =
  None, ai_image_model: str = SHORTS_DEFAULT_AI_IMAGE_MODEL, ai_story_continuity:
  bool = True)` — consumed by `bridge.py` (Task 11).

No dedicated test file exists for `ShortsRunner` today (confirmed: no
`tests/unit/test_shorts_runner.py`) — this task's correctness is covered by the
full regression suite in Task 12, matching the precedent set by the prior
session's `photo_providers`/`footage_source` wiring (which also shipped without
a dedicated runner test file).

- [ ] **Step 1: Add the new import**

In `docu_studio/shorts/shorts_runner.py`, alongside the existing
`from docu_studio.adapters.photos.base import PhotoProvider` import, add:

```python
from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.shorts.shorts_config import SHORTS_DEFAULT_AI_IMAGE_MODEL
```

- [ ] **Step 2: Extend `__init__`**

Find `ShortsRunner.__init__`'s existing `photo_providers: list[PhotoProvider] |
None = None` parameter (stored as `self.photo_providers = photo_providers or
[]`) and the existing `footage_source: str = "video"` parameter (forwarded into
`ShortsConfig(...)`). Add three new parameters at the end of the parameter list
(after the existing `aspect_ratio` param):

```python
        image_gen_provider: ImageGenProvider | None = None,
        ai_image_model: str = SHORTS_DEFAULT_AI_IMAGE_MODEL,
        ai_story_continuity: bool = True,
```

Store the provider alongside the existing `self.photo_providers` assignment:

```python
        self.image_gen_provider = image_gen_provider
```

Forward the model/continuity flags into the existing `ShortsConfig(...)`
construction (alongside where `footage_source=footage_source` is already
passed):

```python
            ai_image_model=ai_image_model,
            ai_story_continuity=ai_story_continuity,
```

- [ ] **Step 3: Wire `generate_shorts_script` and `assemble_short` calls**

In `_execute()`, extend the existing `generate_shorts_script(...)` call (around
line 182) to pass the new mode flags:

```python
        script = generate_shorts_script(
            self.config.topic, self.config.duration_seconds, self.llm,
            tts_provider=self._tts_provider, tts_voice=self._tts_voice,
            footage_source=self.config.footage_source,
            story_continuity=self.config.ai_story_continuity,
        )
```

Extend the existing `assemble_short(...)` call (around line 685/694, matching
where `photo_providers=self.photo_providers` is already passed) to add:

```python
            image_gen_provider=self.image_gen_provider,
```

- [ ] **Step 4: Run the full unit suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: PASS (all tests — `ShortsRunner` has no dedicated tests, but every
module it imports/calls does, and none of their signatures changed in
backward-incompatible ways — all new parameters are optional with defaults)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/shorts/shorts_runner.py
git commit -m "feat(shorts): wire AI image generation into ShortsRunner"
```

---

### Task 11: `bridge.py` wiring

**Files:**
- Modify: `docu_studio/gui/bridge.py`

**Interfaces:**
- Consumes: `build_image_gen_provider(...)` (Task 6), `ShortsRunner(...,
  image_gen_provider=..., ai_image_model=..., ai_story_continuity=...)` (Task 10).

`docu_studio/gui/*` is excluded from the coverage requirement and has no
existing unit-test suite (see Global Constraints) — this task is verified by
manual `grep` checks in Step 3, matching the prior session's approach for the
equivalent `photo_providers`/`footage_source` bridge wiring.

- [ ] **Step 1: Add credential reads and provider construction**

In `docu_studio/gui/bridge.py`'s `start_shorts_run` method, find the existing
block:

```python
            footage_source = config.get("footage_source", "video")
            photo_list = (
                build_photo_providers(pexels_key or "", pixabay_key or "")
                if footage_source == "image" else []
            )
```

Replace it with (photo providers are now needed for both stock-image mode AND
as the AI-image mode's per-sentence failure fallback; AI-image mode also needs
its own generator provider):

```python
            footage_source = config.get("footage_source", "video")
            photo_list = (
                build_photo_providers(pexels_key or "", pixabay_key or "")
                if footage_source in ("image", "ai_image") else []
            )

            image_gen_provider = None
            ai_image_model = config.get("ai_image_model", SHORTS_DEFAULT_AI_IMAGE_MODEL)
            ai_story_continuity = config.get("ai_story_continuity", True)
            if footage_source == "ai_image":
                from docu_studio.adapters.image_gen.factory import build_image_gen_provider
                gemini_key = key_cache.get("docu_studio_gemini")
                replicate_key = key_cache.get("docu_studio_replicate")
                fal_key = key_cache.get("docu_studio_fal")
                image_gen_provider = build_image_gen_provider(
                    ai_image_model, openai_key or "", gemini_key or "",
                    replicate_key or "", fal_key or "",
                )
```

Add the new import near the other imports already inside this method:

```python
            from docu_studio.shorts.shorts_config import SHORTS_DEFAULT_AI_IMAGE_MODEL
```

Note: the `OpenAI` key for AI-image mode reuses `openai_key`, which is already
read earlier in this same method (`key_map["OpenAI"] = key_cache.get(...)` /
`openai_key = key_cache.get("docu_studio_openai")` per the existing code around
line 269-283) — no new read needed for it specifically, only Gemini/Replicate/fal.

- [ ] **Step 2: Pass the new fields into `ShortsRunner(...)`**

Find the existing `ShortsRunner(...)` construction (which already passes
`footage_source=footage_source, photo_providers=photo_list,`), and add:

```python
                image_gen_provider=image_gen_provider,
                ai_image_model=ai_image_model,
                ai_story_continuity=ai_story_continuity,
```

- [ ] **Step 3: Extend `get_settings`/`save_settings` for the three new keys**

In `get_settings` (around line 101, alongside the existing `"openai_key":
key_cache.get("docu_studio_openai"),`), add:

```python
            "gemini_key":      key_cache.get("docu_studio_gemini"),
            "replicate_key":   key_cache.get("docu_studio_replicate"),
            "fal_key":         key_cache.get("docu_studio_fal"),
```

In `save_settings` (around line 135, inside the `_keys()` dict, alongside the
existing `"docu_studio_openai": data.get("openai_key", ""),`), add:

```python
                    "docu_studio_gemini":       data.get("gemini_key",    ""),
                    "docu_studio_replicate":    data.get("replicate_key", ""),
                    "docu_studio_fal":          data.get("fal_key",       ""),
```

- [ ] **Step 4: Manually verify the wiring**

Run:
```bash
grep -n "ai_image_model\|ai_story_continuity\|image_gen_provider\|docu_studio_gemini\|docu_studio_replicate\|docu_studio_fal" "docu_studio/gui/bridge.py"
```
Expected: every reference above appears — credential reads, provider
construction, `ShortsRunner(...)` args, and both settings dict directions.

Run a Python import smoke check (catches syntax/import errors without starting
the GUI):
```bash
.venv/bin/python -c "import docu_studio.gui.bridge"
```
Expected: no output, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add docu_studio/gui/bridge.py
git commit -m "feat(shorts): wire AI-image provider construction and credentials into bridge"
```

---

### Task 12: GUI — Settings keys, footage-source option, model/continuity/cost UI

**Files:**
- Modify: `docu_studio/gui/web/index.html`
- Modify: `docu_studio/gui/web/app.js`
- Modify: `docu_studio/gui/webview_app.py`

**Interfaces:**
- Produces: `start_shorts_run` payload gains `ai_image_model` and
  `ai_story_continuity` fields — consumed by `bridge.py` (Task 11, already
  wired to read `config.get("ai_image_model", ...)` /
  `config.get("ai_story_continuity", ...)`).

No automated test coverage for this layer (see Global Constraints) — verified
by manual `grep` checks in Step 5.

- [ ] **Step 1: Add the "AI-generated images" option to the footage-source select**

In `docu_studio/gui/web/index.html`, find the existing `#footage-source-row`
block (line 424) and add a third `<option>`:

```html
        <!-- Footage source (short/reel) -->
        <div id="footage-source-row" class="mt-4" style="display:none">
          <label class="text-sm font-medium text-dim block">Footage source</label>
          <select id="shorts-footage-source-select" onchange="onFootageSourceChange(this.value)"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="video">Video clips — stock footage</option>
            <option value="image">Images — stock photos with Ken Burns motion</option>
            <option value="ai_image">AI-generated images — unique art per scene</option>
          </select>
        </div>
```

(Only the `onchange` attribute and the new third `<option>` are new; the rest of
the block is unchanged.)

- [ ] **Step 2: Add the AI-image model/continuity/cost rows**

Immediately after the `#footage-source-row` block (and before the existing
`<!-- Aspect ratio (short/reel) -->` block), add:

```html
        <!-- AI image model (short/reel, only when footage_source = ai_image) -->
        <div id="ai-image-model-row" class="mt-4" style="display:none">
          <label class="text-sm font-medium text-dim block">AI image model</label>
          <select id="shorts-ai-image-model-select" onchange="_updateAiImageCostEstimate()"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="replicate_flux_schnell">Replicate — FLUX.1 Schnell (cheap, ~$0.003/image)</option>
            <option value="fal_flux_schnell">fal.ai — FLUX.1 Schnell (cheap, ~$0.003/image)</option>
            <option value="replicate_sdxl">Replicate — SDXL (cheap, ~$0.0055/image)</option>
            <option value="replicate_flux_dev">Replicate — FLUX.1 Dev (mid, ~$0.025/image)</option>
            <option value="fal_flux_dev">fal.ai — FLUX.1 Dev (mid, ~$0.025/image)</option>
            <option value="gemini_nano_banana">Google — Nano Banana (mid, ~$0.04/image)</option>
            <option value="openai_gpt_image_1">OpenAI — GPT-Image-1 (premium, ~$0.07/image)</option>
            <option value="gemini_nano_banana_pro">Google — Nano Banana Pro (premium, ~$0.15/image)</option>
          </select>
        </div>

        <!-- AI story continuity toggle (short/reel) -->
        <div id="ai-story-continuity-row" class="mt-4 flex items-center justify-between" style="display:none">
          <div>
            <label class="text-sm font-medium text-dim block">Connected story</label>
            <p class="text-xs text-faint mt-0.5">On: one consistent style/character across every scene. Off: each scene generated independently.</p>
          </div>
          <input id="ai-story-continuity-toggle" type="checkbox" checked class="toggle-switch">
        </div>

        <!-- AI cost estimate (short/reel) -->
        <div id="ai-cost-estimate-row" class="mt-2 text-xs text-faint" style="display:none"></div>
```

- [ ] **Step 3: Add the three new API-key Settings rows**

In `docu_studio/gui/web/index.html`, add a new card after the existing
"CARD 4: Topic Discovery" card (which ends around line 1092, right before
`<!-- CARD 4b: Music -->`):

```html
      <!-- CARD 4c: AI Image Generation -->
      <div class="anim-card bg-card border border-border rounded-xl mb-5 overflow-hidden">
        <div class="h-0.5 w-full bg-indigo-500"></div>
        <div class="px-6 py-4 border-b border-border">
          <span class="font-semibold text-white text-sm">AI Image Generation</span>
        </div>
        <div class="px-6 py-5 space-y-5">
          <p class="text-xs text-faint">
            Used by the Short/Reel "AI-generated images" footage source. The OpenAI key
            above (Script Generation card) is reused for OpenAI's image model.
          </p>
          <div>
            <label class="text-sm font-medium text-dim block mb-2">Google Gemini API Key</label>
            <div class="flex gap-2">
              <input type="password" id="gemini-key" class="flex-1 bg-input border border-border rounded-lg px-4 py-2.5 text-white text-sm font-mono focus:border-accent focus:outline-none">
              <button onclick="toggleReveal('gemini-key', this)" class="px-4 py-2.5 bg-hover border border-border rounded-lg text-dim text-sm hover:text-white transition-colors">Reveal</button>
            </div>
          </div>
          <div>
            <label class="text-sm font-medium text-dim block mb-2">Replicate API Token</label>
            <div class="flex gap-2">
              <input type="password" id="replicate-key" class="flex-1 bg-input border border-border rounded-lg px-4 py-2.5 text-white text-sm font-mono focus:border-accent focus:outline-none">
              <button onclick="toggleReveal('replicate-key', this)" class="px-4 py-2.5 bg-hover border border-border rounded-lg text-dim text-sm hover:text-white transition-colors">Reveal</button>
            </div>
          </div>
          <div>
            <label class="text-sm font-medium text-dim block mb-2">fal.ai API Key</label>
            <div class="flex gap-2">
              <input type="password" id="fal-key" class="flex-1 bg-input border border-border rounded-lg px-4 py-2.5 text-white text-sm font-mono focus:border-accent focus:outline-none">
              <button onclick="toggleReveal('fal-key', this)" class="px-4 py-2.5 bg-hover border border-border rounded-lg text-dim text-sm hover:text-white transition-colors">Reveal</button>
            </div>
          </div>
        </div>
      </div>
```

- [ ] **Step 4: Wire visibility, cost estimate, settings load/save, and payload in `app.js`**

In `docu_studio/gui/web/app.js`, add the row-visibility toggle to `startConfig`
(right after the existing `_q('footage-source-row').style.display = ...` line
265):

```javascript
  _q('footage-source-row').style.display = mode === 'short' ? '' : 'none';
  if (mode === 'short') onFootageSourceChange(_q('shorts-footage-source-select').value);
```

Add the new `onFootageSourceChange` function, right after the existing
`onFootageChange` function (after line 124):

```javascript
function onFootageSourceChange(value) {
  const isAiImage = value === 'ai_image';
  _q('ai-image-model-row').style.display = isAiImage ? '' : 'none';
  _q('ai-story-continuity-row').style.display = isAiImage ? '' : 'none';
  _q('ai-cost-estimate-row').style.display = isAiImage ? '' : 'none';
  if (isAiImage) _updateAiImageCostEstimate();
}

const _AI_IMAGE_PRICES_USD = {
  replicate_flux_schnell: 0.003,
  fal_flux_schnell: 0.003,
  replicate_sdxl: 0.0055,
  replicate_flux_dev: 0.025,
  fal_flux_dev: 0.025,
  gemini_nano_banana: 0.04,
  openai_gpt_image_1: 0.07,
  gemini_nano_banana_pro: 0.15,
};

function _updateAiImageCostEstimate() {
  const model = _q('shorts-ai-image-model-select').value;
  const price = _AI_IMAGE_PRICES_USD[model] || 0;
  // Rough scene-count estimate: one image per ~4.5s of narration at the
  // Shorts default pace — matches the segment cadence the pipeline actually
  // produces closely enough for a pre-run estimate, not exact billing.
  const secs = parseInt(_q('shorts-duration-slider').value) || 30;
  const sceneCount = Math.max(1, Math.round(secs / 4.5));
  const total = (sceneCount * price).toFixed(3);
  _q('ai-cost-estimate-row').textContent =
    `Estimated cost: ~${sceneCount} images × $${price.toFixed(3)} = ~$${total}`;
}
```

Wire the duration slider to also refresh the cost estimate. The existing
`updateShortsDurationHint` function (app.js line 691, already bound to the
duration slider's `input` event at line 981) is:

```javascript
function updateShortsDurationHint() {
  const secs = parseInt(_q('shorts-duration-slider').value) || 30;
  _q('shorts-duration-label').textContent = secs + ' s';
  const words = Math.round((secs / 60) * 170);
  _q('shorts-duration-hint').textContent = `Target: ${secs}s ≈ ${words} words of narration`;
}
```

Add one line at its end so every duration change also refreshes the cost
estimate when AI-image mode is active:

```javascript
function updateShortsDurationHint() {
  const secs = parseInt(_q('shorts-duration-slider').value) || 30;
  _q('shorts-duration-label').textContent = secs + ' s';
  const words = Math.round((secs / 60) * 170);
  _q('shorts-duration-hint').textContent = `Target: ${secs}s ≈ ${words} words of narration`;
  if (_q('shorts-footage-source-select').value === 'ai_image') _updateAiImageCostEstimate();
}
```

Extend the settings-load block (right after the existing line 51
`_q('groq-key').value = s.groq_key || '';`):

```javascript
    _q('gemini-key').value     = s.gemini_key     || '';
    _q('replicate-key').value  = s.replicate_key  || '';
    _q('fal-key').value        = s.fal_key        || '';
```

Extend the settings-save payload (right after the existing line 189
`groq_key: _q('groq-key').value,`):

```javascript
    gemini_key:      _q('gemini-key').value,
    replicate_key:   _q('replicate-key').value,
    fal_key:         _q('fal-key').value,
```

Extend the `start_shorts_run` submit payload (right after the existing line 780
`footage_source: _q('shorts-footage-source-select').value,`):

```javascript
      ai_image_model: _q('shorts-ai-image-model-select').value,
      ai_story_continuity: _q('ai-story-continuity-toggle').checked,
```

- [ ] **Step 5: Bump the cache-busting version and manually verify**

In `docu_studio/gui/webview_app.py`, bump the cache-bust query string:

```python
the_url = str(WEB_DIR / "index.html") + "?v=17"
```

(Was `?v=16`.)

Run the wiring verification:
```bash
grep -n "ai-image-model-row\|ai-story-continuity\|ai-cost-estimate-row\|onFootageSourceChange\|gemini-key\|replicate-key\|fal-key\|ai_image_model\|ai_story_continuity" \
  docu_studio/gui/web/index.html docu_studio/gui/web/app.js
```
Expected: every id/handler introduced above appears in both files, with
matching id spelling between the `<input>`/`<select>` declarations in
`index.html` and the `_q(...)` lookups in `app.js` (a mismatched id is the most
common bug in this kind of wiring — the `grep` output must show identical
strings on both sides).

Confirm the cache-bust bump:
```bash
grep -n '"?v=' docu_studio/gui/webview_app.py
```
Expected: `?v=17`.

- [ ] **Step 6: Commit**

```bash
git add docu_studio/gui/web/index.html docu_studio/gui/web/app.js docu_studio/gui/webview_app.py
git commit -m "feat(shorts): add AI-image model/continuity/cost UI and provider key settings"
```

---

### Task 13: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit test suite**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: PASS — every test from Tasks 1-10 plus all pre-existing tests. If any
pre-existing test fails, diff against a clean `git stash` run (per the prior
session's convention) to confirm it's pre-existing and unrelated before
proceeding, rather than assuming it's fine.

- [ ] **Step 2: Run the integration suite**

Run: `.venv/bin/python -m pytest tests/integration/ -v`
Expected: PASS (same pre-existing-failure caveat as Step 1 — this project has
some pre-existing unrelated integration-test gaps documented in the prior
session, e.g. a missing `edge_tts_adapter` module; confirm any failure here
matches that known set before treating this task as done).

- [ ] **Step 3: Full-repo import smoke check**

Run: `.venv/bin/python -c "import docu_studio.gui.bridge; import docu_studio.shorts.shorts_runner; import docu_studio.adapters.image_gen.factory"`
Expected: no output, exit code 0 — confirms no circular imports were
introduced by `shorts_config.py` importing from `adapters/image_gen/factory.py`.

- [ ] **Step 4: Commit (only if Steps 1-3 required any fixes)**

If everything passed cleanly with no changes needed, there is nothing to
commit for this task — it's a verification checkpoint, not a code change.

---

## Explicitly out of scope (carried over from the spec)

- No live, paid end-to-end run as part of this plan — verified via mocked
  adapters only. A live run happens only if/when the user explicitly asks for
  one.
- No dynamic/live pricing lookups.
- No Midjourney support (no official API).
- No per-image resolution/quality override beyond each preset's fixed defaults.
- No mid-run cost tracking/actual-spend display.
