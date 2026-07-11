# Slideshow Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add topic-based photo fetch (Pexels/Pixabay) and LLM-generated narration script to the Slideshow pipeline, feeding both into Phase 1's existing `image_paths`/`script_text` pipeline unchanged.

**Architecture:** Two independent, self-contained additions — a new `docu_studio/adapters/photos/` package (photo search) plus a fresh resilient downloader and LLM-prompt module inside `docu_studio/slideshow/` — wired into `bridge.py` as two new synchronous pre-run methods and into the existing Slideshow config screen as additive GUI controls. Zero changes to `SlideshowConfig`, `slideshow_images.py`, `slideshow_motion.py`, `slideshow_ffmpeg.py`, `slideshow_assembly.py`, or `SlideshowRunner`.

**Tech Stack:** Python 3.11+, `requests`, `pytest` + `responses` (HTTP-mocked integration tests) + `unittest.mock` (unit tests), pywebview/QtWebEngine GUI (vanilla JS, Tailwind utility classes).

## Global Constraints

- Correct venv is `.venv/` — always use `.venv/bin/python`. Never `venv/`.
- Always restart before testing any bridge/GUI change (Python doesn't hot-reload): `pkill -f docu_studio 2>/dev/null` then `DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Test baseline going into this plan: 24 failed / 478 passed / 1 error (pre-existing, unrelated to Slideshow — confirmed at the end of the Phase 1 session). Confirm this is still what `pytest -q --continue-on-collection-errors` shows before Task 1; after each task, the only change should be new tests added, all passing — the 24/1 pre-existing failures/error must stay exactly as they are.
- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files — new adapter files under `adapters/photos/` are fine), `history/`, `licensing.py`, or existing test files unless fixing an actual bug in them.
- Zero dependency on `docu_studio/shorts/` — the resilient downloader is a fresh, self-contained copy of `shorts_footage_download.py`'s pattern inside `docu_studio/slideshow/`, not an import.
- Commit after each task. Do not push to origin without explicit go-ahead.
- HTTP-mocked adapter tests live in `tests/integration/` (matching `test_pexels_adapter.py`/`test_pixabay_adapter.py`); no-network unit tests live in `tests/unit/` (matching `test_shorts_footage_download.py`).
- Cache-bust `?v=N` in `docu_studio/gui/webview_app.py` after any HTML/JS edit — the current value is `?v=11` (verified by reading the file directly before Task 7; re-verify before editing, don't assume it's still 11).
- All new HTTP calls use a 15-second `timeout` for search requests (matching the existing footage adapters) and `(10, 30)` connect/read timeouts for downloads (matching `shorts_footage_download.py`).

---

### Task 1: Photo provider base + Pexels photos adapter

**Files:**
- Create: `docu_studio/adapters/photos/__init__.py` (empty)
- Create: `docu_studio/adapters/photos/base.py`
- Create: `docu_studio/adapters/photos/pexels_photos_adapter.py`
- Test: `tests/integration/test_pexels_photos_adapter.py`

**Interfaces:**
- Produces: `PhotoResult` (frozen dataclass: `url: str, width: int, height: int, photo_id: str = ""`), `PhotoProvider(ABC)` with `search(self, query: str, page: int = 1) -> list[PhotoResult]`, and `PexelsPhotosAdapter(PhotoProvider)` with `__init__(self, api_key: str)`.

- [ ] **Step 1: Create the empty package `__init__.py`**

```bash
mkdir -p "docu_studio/adapters/photos"
touch "docu_studio/adapters/photos/__init__.py"
```

- [ ] **Step 2: Write `docu_studio/adapters/photos/base.py`**

```python
"""PhotoProvider ABC and PhotoResult dataclass — still-image search, distinct
from FootageProvider/FootageClip (docu_studio/adapters/footage/base.py),
which are duration-oriented and don't fit photos."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PhotoResult:
    url: str
    width: int
    height: int
    # Stable provider-native photo ID (Pexels/Pixabay numeric id, as a
    # string). "" when a provider/call site doesn't populate it. Callers
    # that need to dedupe should prefer this over `url` — the same
    # underlying photo can be returned with a different URL across separate
    # search calls (e.g. different size variants).
    photo_id: str = ""


class PhotoProvider(ABC):
    @abstractmethod
    def search(self, query: str, page: int = 1) -> list[PhotoResult]:
        """Return photos matching *query*."""
```

- [ ] **Step 3: Write the failing test for `PexelsPhotosAdapter`**

Create `tests/integration/test_pexels_photos_adapter.py`:

```python
"""HTTP-mocked integration tests for PexelsPhotosAdapter (the photo search
endpoint, distinct from the existing video-search PexelsAdapter)."""
from __future__ import annotations

import responses as resp_lib

from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.adapters.photos.pexels_photos_adapter import PexelsPhotosAdapter

_PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"

_SAMPLE_RESPONSE = {
    "photos": [
        {"id": 1, "width": 1920, "height": 1080, "src": {"large": "https://images.pexels.com/1.jpg"}},
        {"id": 2, "width": 1280, "height": 720, "src": {"large": "https://images.pexels.com/2.jpg"}},
    ]
}


def _make_adapter() -> PexelsPhotosAdapter:
    return PexelsPhotosAdapter(api_key="pexels-fake-key")


class TestPexelsPhotosAdapterSearch:
    @resp_lib.activate
    def test_returns_list_of_photo_results(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photos = adapter.search("mountains")
        assert isinstance(photos, list)
        assert all(isinstance(p, PhotoResult) for p in photos)
        assert len(photos) == 2

    @resp_lib.activate
    def test_photos_have_expected_fields(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photo = adapter.search("mountains")[0]
        assert photo.url == "https://images.pexels.com/1.jpg"
        assert photo.width == 1920
        assert photo.height == 1080
        assert photo.photo_id == "1"

    @resp_lib.activate
    def test_returns_empty_list_on_404(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={}, status=404)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_returns_empty_list_on_401(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={}, status=401)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_returns_empty_list_on_429(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={}, status=429)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_skips_photo_missing_large_src(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={
            "photos": [{"id": 3, "width": 800, "height": 600, "src": {}}]
        }, status=200)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_pexels_photos_adapter.py -v`
Expected: FAIL / collection error — `docu_studio.adapters.photos.pexels_photos_adapter` doesn't exist yet.

- [ ] **Step 5: Write `docu_studio/adapters/photos/pexels_photos_adapter.py`**

```python
"""Pexels photo search adapter — the photo endpoint, distinct from
docu_studio/adapters/footage/pexels_adapter.py's video endpoint."""
from __future__ import annotations

import logging

import requests

from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult
from docu_studio.retry import retry

_API_URL = "https://api.pexels.com/v1/search"
_log = logging.getLogger(__name__)


class PexelsPhotosAdapter(PhotoProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def search(self, query: str, page: int = 1) -> list[PhotoResult]:
        try:
            response = requests.get(
                _API_URL,
                headers={"Authorization": self._api_key},
                params={"query": query, "per_page": 20, "page": page},
                timeout=15,
            )
        except requests.Timeout:
            _log.warning("Pexels photos: request timed out")
            return []
        except (ConnectionResetError, ConnectionError) as exc:
            _log.warning("Pexels photos: connection failed: %s", exc)
            return []

        status = response.status_code
        if status == 429:
            _log.warning("Pexels photos: rate limit hit (429), skipping")
            return []
        if status in (401, 403):
            _log.warning("Pexels photos: invalid API key (%d)", status)
            return []
        if status == 400:
            _log.warning("Pexels photos: bad request (400): %s", response.text[:200])
            return []
        if status == 404:
            return []
        if status != 200:
            _log.warning("Pexels photos: HTTP %d", status)
            return []

        data = response.json()
        photos: list[PhotoResult] = []
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            url = src.get("large", "")
            if not url:
                continue
            photos.append(PhotoResult(
                url=url,
                width=photo.get("width", 0),
                height=photo.get("height", 0),
                photo_id=str(photo.get("id", "")),
            ))
        return photos
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_pexels_photos_adapter.py -v`
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add docu_studio/adapters/photos/__init__.py docu_studio/adapters/photos/base.py \
  docu_studio/adapters/photos/pexels_photos_adapter.py tests/integration/test_pexels_photos_adapter.py
git commit -m "feat(slideshow): add PhotoProvider base and Pexels photo search adapter"
```

---

### Task 2: Pixabay photos adapter

**Files:**
- Create: `docu_studio/adapters/photos/pixabay_photos_adapter.py`
- Test: `tests/integration/test_pixabay_photos_adapter.py`

**Interfaces:**
- Consumes: `PhotoProvider`, `PhotoResult` from `docu_studio.adapters.photos.base` (Task 1).
- Produces: `PixabayPhotosAdapter(PhotoProvider)` with `__init__(self, api_key: str)`.

- [ ] **Step 1: Write the failing test for `PixabayPhotosAdapter`**

Create `tests/integration/test_pixabay_photos_adapter.py`:

```python
"""HTTP-mocked integration tests for PixabayPhotosAdapter (the photo search
endpoint, distinct from the existing video-search PixabayAdapter)."""
from __future__ import annotations

import responses as resp_lib

from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.adapters.photos.pixabay_photos_adapter import PixabayPhotosAdapter

_PIXABAY_PHOTO_URL = "https://pixabay.com/api/"

_SAMPLE_RESPONSE = {
    "hits": [
        {"id": 10, "imageWidth": 1920, "imageHeight": 1080, "largeImageURL": "https://cdn.pixabay.com/10.jpg"},
        {"id": 11, "imageWidth": 1280, "imageHeight": 720, "largeImageURL": "https://cdn.pixabay.com/11.jpg"},
    ]
}


def _make_adapter() -> PixabayPhotosAdapter:
    return PixabayPhotosAdapter(api_key="pixabay-fake-key")


class TestPixabayPhotosAdapterSearch:
    @resp_lib.activate
    def test_returns_list_of_photo_results(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photos = adapter.search("mountains")
        assert isinstance(photos, list)
        assert all(isinstance(p, PhotoResult) for p in photos)
        assert len(photos) == 2

    @resp_lib.activate
    def test_photos_have_expected_fields(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photo = adapter.search("mountains")[0]
        assert photo.url == "https://cdn.pixabay.com/10.jpg"
        assert photo.width == 1920
        assert photo.height == 1080
        assert photo.photo_id == "10"

    @resp_lib.activate
    def test_returns_empty_list_on_500(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json={}, status=500)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    def test_returns_empty_list_with_no_api_key(self) -> None:
        adapter = PixabayPhotosAdapter(api_key="")
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_skips_hit_missing_large_image_url(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json={
            "hits": [{"id": 12, "imageWidth": 800, "imageHeight": 600}]
        }, status=200)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_pixabay_photos_adapter.py -v`
Expected: FAIL / collection error — module doesn't exist yet.

- [ ] **Step 3: Write `docu_studio/adapters/photos/pixabay_photos_adapter.py`**

```python
"""Pixabay photo search adapter — the photo endpoint, distinct from
docu_studio/adapters/footage/pixabay_adapter.py's video endpoint."""
from __future__ import annotations

import logging

import requests

from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult
from docu_studio.retry import retry

_API_URL = "https://pixabay.com/api/"
_log = logging.getLogger(__name__)


class PixabayPhotosAdapter(PhotoProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def search(self, query: str, page: int = 1) -> list[PhotoResult]:
        if not self._api_key:
            _log.warning("Pixabay photos: no API key configured")
            return []

        try:
            response = requests.get(
                _API_URL,
                params={
                    "key": self._api_key,
                    "q": query,
                    "per_page": 20,
                    "page": page,
                    "image_type": "photo",
                },
                timeout=15,
            )
        except requests.Timeout:
            _log.warning("Pixabay photos: request timed out")
            return []
        except (ConnectionResetError, ConnectionError) as exc:
            _log.warning("Pixabay photos: connection failed, skipping: %s", exc)
            return []
        except Exception as exc:
            _log.warning("Pixabay photos request failed: %s", exc)
            return []

        status = response.status_code
        if status == 429:
            _log.warning("Pixabay photos: rate limit hit (429), skipping")
            return []
        if status in (401, 403):
            _log.warning("Pixabay photos: invalid API key (%d)", status)
            return []
        if status == 400:
            _log.warning("Pixabay photos: bad request (400): %s", response.text[:200])
            return []
        if status != 200:
            _log.warning("Pixabay photos: HTTP %d", status)
            return []

        data = response.json()
        photos: list[PhotoResult] = []
        for hit in data.get("hits", []):
            url = hit.get("largeImageURL", "")
            if not url:
                continue
            photos.append(PhotoResult(
                url=url,
                width=hit.get("imageWidth", 0),
                height=hit.get("imageHeight", 0),
                photo_id=str(hit.get("id", "")),
            ))
        return photos
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_pixabay_photos_adapter.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/adapters/photos/pixabay_photos_adapter.py tests/integration/test_pixabay_photos_adapter.py
git commit -m "feat(slideshow): add Pixabay photo search adapter"
```

---

### Task 3: Photo provider factory

**Files:**
- Create: `docu_studio/adapters/photos/factory.py`
- Test: `tests/unit/test_photos_factory.py`

**Interfaces:**
- Consumes: `PexelsPhotosAdapter` (Task 1), `PixabayPhotosAdapter` (Task 2).
- Produces: `build_photo_providers(pexels_key: str, pixabay_key: str) -> list[PhotoProvider]` — Pexels always included (even with an empty key, mirroring the existing footage factory), Pixabay included only if `pixabay_key` is truthy. Fixed order: Pexels primary, Pixabay fallback.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_photos_factory.py`:

```python
"""Unit tests for the photo-provider factory: Pexels always included, Pixabay
only when a key is configured."""
from __future__ import annotations

from docu_studio.adapters.photos.factory import build_photo_providers
from docu_studio.adapters.photos.pexels_photos_adapter import PexelsPhotosAdapter
from docu_studio.adapters.photos.pixabay_photos_adapter import PixabayPhotosAdapter


class TestBuildPhotoProviders:
    def test_pexels_always_included(self) -> None:
        providers = build_photo_providers(pexels_key="", pixabay_key="")
        assert len(providers) == 1
        assert isinstance(providers[0], PexelsPhotosAdapter)

    def test_pixabay_included_when_key_present(self) -> None:
        providers = build_photo_providers(pexels_key="pk", pixabay_key="pixk")
        assert len(providers) == 2
        assert isinstance(providers[0], PexelsPhotosAdapter)
        assert isinstance(providers[1], PixabayPhotosAdapter)

    def test_pixabay_excluded_when_key_missing(self) -> None:
        providers = build_photo_providers(pexels_key="pk", pixabay_key="")
        assert len(providers) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_photos_factory.py -v`
Expected: FAIL / collection error — `docu_studio.adapters.photos.factory` doesn't exist yet.

- [ ] **Step 3: Write `docu_studio/adapters/photos/factory.py`**

```python
"""Factory for photo adapters."""
from __future__ import annotations

import logging

from docu_studio.adapters.photos.base import PhotoProvider

_log = logging.getLogger(__name__)


def build_photo_providers(pexels_key: str, pixabay_key: str) -> list[PhotoProvider]:
    from docu_studio.adapters.photos.pexels_photos_adapter import PexelsPhotosAdapter

    providers: list[PhotoProvider] = [PexelsPhotosAdapter(api_key=pexels_key)]

    if pixabay_key:
        from docu_studio.adapters.photos.pixabay_photos_adapter import PixabayPhotosAdapter
        providers.append(PixabayPhotosAdapter(api_key=pixabay_key))

    active = [type(p).__name__.removesuffix("Adapter") for p in providers]
    _log.info("Photo providers: %s", active)
    return providers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_photos_factory.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/adapters/photos/factory.py tests/unit/test_photos_factory.py
git commit -m "feat(slideshow): add photo provider factory"
```

---

### Task 4: Resilient photo downloader + topic-fetch orchestration

**Files:**
- Create: `docu_studio/slideshow/slideshow_photo_download.py`
- Test: `tests/unit/test_slideshow_photo_download.py`

**Interfaces:**
- Consumes: `PhotoProvider`, `PhotoResult` from `docu_studio.adapters.photos.base` (Task 1).
- Produces: `build_download_session() -> requests.Session`, `download_photo_resilient(session, url: str, dest: str, last_request_at: dict[str, float] | None = None) -> str`, `fetch_topic_images(topic: str, count: int, providers: list[PhotoProvider], dest_dir: Path) -> list[str]` — raises `ValueError` if `count <= 0`, raises `RuntimeError` if zero photos download successfully, otherwise returns local file paths (fewer than `count` if the capped pool runs out).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_slideshow_photo_download.py`:

```python
"""Unit tests for the slideshow-only resilient photo downloader (mirrors
tests/unit/test_shorts_footage_download.py's structure) plus the
fetch_topic_images over-fetch/dedup/partial-success orchestration. No real
network calls — session and providers are always mocks."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.slideshow.slideshow_photo_download import (
    BROWSER_USER_AGENT,
    build_download_session,
    download_photo_resilient,
    fetch_topic_images,
)


def _ok_response(body: bytes = b"photo-bytes") -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [body]
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _http_error_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    error = requests.exceptions.HTTPError(f"{status_code} error")
    error.response = response
    response.raise_for_status.side_effect = error
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestRetryOnTransientFailures:
    def test_retries_on_connection_error_and_succeeds_on_later_attempt(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.side_effect = [
            requests.exceptions.ConnectionError("reset"),
            _ok_response(b"real-photo-data"),
        ]
        dest = str(tmp_path / "photo.jpg")

        with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep"):
            result = download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        assert result == dest
        assert Path(dest).read_bytes() == b"real-photo-data"
        assert session.get.call_count == 2

    def test_retries_on_5xx_and_429(self, tmp_path: Path) -> None:
        for status in (429, 500, 503):
            session = MagicMock()
            session.get.side_effect = [_http_error_response(status), _ok_response()]
            dest = str(tmp_path / f"photo_{status}.jpg")

            with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep"):
                result = download_photo_resilient(session, "https://cdn.pixabay.com/a.jpg", dest)

            assert result == dest
            assert session.get.call_count == 2

    def test_gives_up_after_max_attempts(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("reset")
        dest = str(tmp_path / "photo.jpg")

        with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep"):
            with pytest.raises(requests.exceptions.ConnectionError):
                download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        assert session.get.call_count == 3


class TestNoRetryOnClientErrors:
    def test_does_not_retry_on_404(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _http_error_response(404)
        dest = str(tmp_path / "photo.jpg")

        with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep") as mock_sleep:
            with pytest.raises(requests.exceptions.HTTPError):
                download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        assert session.get.call_count == 1
        mock_sleep.assert_not_called()


class TestSessionAndHeaders:
    def test_build_download_session_sets_browser_user_agent(self) -> None:
        session = build_download_session()
        assert session.headers["User-Agent"] == BROWSER_USER_AGENT

    def test_get_called_with_stream_and_explicit_connect_read_timeouts(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "photo.jpg")

        download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        _args, kwargs = session.get.call_args
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == (10, 30)


class TestSameHostPacing:
    def test_sleeps_when_last_request_to_same_host_was_recent(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "photo.jpg")
        last_request_at = {"images.pexels.com": 1000.0}

        with patch("docu_studio.slideshow.slideshow_photo_download.time.monotonic", return_value=1000.05):
            with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep") as mock_sleep:
                download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest, last_request_at)

        mock_sleep.assert_called_once()
        (delay,), _ = mock_sleep.call_args
        assert 0.0 < delay <= 0.5


class TestFetchTopicImages:
    def test_downloads_up_to_count_and_returns_local_paths(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url=f"https://images.pexels.com/{i}.jpg", width=1920, height=1080, photo_id=str(i))
            for i in range(5)
        ]
        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
            side_effect=lambda session, url, dest, last=None: dest,
        ):
            paths = fetch_topic_images("mountains", 3, [provider], tmp_path)

        assert len(paths) == 3

    def test_caps_candidate_pool_at_ceil_count_times_1_5(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url=f"https://images.pexels.com/{i}.jpg", width=1920, height=1080, photo_id=str(i))
            for i in range(20)
        ]
        attempted_urls: list[str] = []

        def _always_fail(session, url, dest, last=None):
            attempted_urls.append(url)
            raise requests.exceptions.ConnectionError("boom")

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
            side_effect=_always_fail,
        ):
            with pytest.raises(RuntimeError):
                fetch_topic_images("mountains", 4, [provider], tmp_path)

        # ceil(4 * 1.5) = 6 — the pool is capped there even though the
        # provider returned 20 candidates, so at most 6 download attempts
        assert len(attempted_urls) == 6

    def test_dedupes_by_photo_id_across_providers(self, tmp_path: Path) -> None:
        shared = PhotoResult(url="https://images.pexels.com/dup.jpg", width=1920, height=1080, photo_id="42")
        provider_a = MagicMock()
        provider_a.search.return_value = [shared]
        provider_b = MagicMock()
        provider_b.search.return_value = [
            PhotoResult(url="https://cdn.pixabay.com/dup-different-url.jpg", width=1920, height=1080, photo_id="42"),
            PhotoResult(url="https://cdn.pixabay.com/unique.jpg", width=1920, height=1080, photo_id="99"),
        ]

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
            side_effect=lambda session, url, dest, last=None: dest,
        ):
            paths = fetch_topic_images("mountains", 2, [provider_a, provider_b], tmp_path)

        assert len(paths) == 2  # only 2 distinct photo_ids exist (42, 99)

    def test_partial_success_returns_what_succeeded(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url=f"https://images.pexels.com/{i}.jpg", width=1920, height=1080, photo_id=str(i))
            for i in range(5)
        ]

        def _flaky_download(session, url, dest, last=None):
            if url.endswith("0.jpg"):
                raise requests.exceptions.ConnectionError("boom")
            return dest

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
            side_effect=_flaky_download,
        ):
            paths = fetch_topic_images("mountains", 5, [provider], tmp_path)

        assert 0 < len(paths) < 5

    def test_zero_successful_downloads_raises(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url="https://images.pexels.com/1.jpg", width=1920, height=1080, photo_id="1"),
        ]

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(RuntimeError):
                fetch_topic_images("mountains", 1, [provider], tmp_path)

    def test_zero_or_negative_count_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            fetch_topic_images("mountains", 0, [MagicMock()], tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_photo_download.py -v`
Expected: FAIL / collection error — module doesn't exist yet.

- [ ] **Step 3: Write `docu_studio/slideshow/slideshow_photo_download.py`**

```python
"""Resilient photo downloads for the Slideshow topic-fetch flow — a
self-contained copy of the hardened pattern in
docu_studio/shorts/shorts_footage_download.py (session + browser UA,
(10, 30)s connect/read timeouts, retry with backoff+jitter on transient
failures only, same-host pacing). Not imported from shorts/, per the Phase 1
design decision to defer all shared infrastructure extraction with shorts/
until a phase actually needs it.
"""
from __future__ import annotations

import logging
import math
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult

_log = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CONNECT_TIMEOUT_SECONDS = 10
_READ_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.5
_BACKOFF_JITTER_SECONDS = (0.0, 0.5)
_RETRIABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_SAME_HOST_DELAY_RANGE_SECONDS = (0.2, 0.5)
_MAX_POOL_MULTIPLIER = 1.5


def build_download_session() -> requests.Session:
    """One Session per fetch's worth of downloads, for connection pooling/reuse."""
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_USER_AGENT})
    return session


def _is_retriable(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        return response is not None and response.status_code in _RETRIABLE_STATUS_CODES
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def download_photo_resilient(
    session: requests.Session,
    url: str,
    dest: str,
    last_request_at: dict[str, float] | None = None,
) -> str:
    """Download *url* to *dest*, retrying transient failures (connection
    resets, timeouts, 5xx/429) with exponential backoff + jitter. Client
    errors (4xx other than 429) are not retried. If *last_request_at* is
    given, paces sequential requests to the same host with a small random
    delay. Raises the final exception if all attempts are exhausted.
    """
    host = urlparse(url).netloc
    if last_request_at is not None:
        last = last_request_at.get(host)
        if last is not None:
            min_gap = random.uniform(*_SAME_HOST_DELAY_RANGE_SECONDS)
            remaining = min_gap - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        if last_request_at is not None:
            last_request_at[host] = time.monotonic()
        try:
            with session.get(
                url, stream=True,
                timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
            ) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
            return dest
        except Exception as exc:
            if attempt >= _MAX_ATTEMPTS or not _is_retriable(exc):
                raise
            backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(*_BACKOFF_JITTER_SECONDS)
            _log.info(
                "download attempt %d/%d for %s after %s, retrying in %.1fs",
                attempt, _MAX_ATTEMPTS, url, type(exc).__name__, backoff,
            )
            time.sleep(backoff)
    raise AssertionError("unreachable")  # pragma: no cover


def _dedup_key(photo: PhotoResult) -> str:
    return photo.photo_id if photo.photo_id else photo.url


def fetch_topic_images(
    topic: str, count: int, providers: list[PhotoProvider], dest_dir: Path,
) -> list[str]:
    """Search *providers* in order for *topic*, download up to *count* distinct
    photos into *dest_dir*, and return the local file paths of whichever
    downloads succeeded (in pool order).

    Over-fetches a candidate pool capped at ceil(count * 1.5) — the same
    guard shorts_assembly.py uses for footage — so a few failed downloads
    don't require a second round-trip to the providers. Raises RuntimeError
    if zero photos download successfully; returns fewer than *count* (with a
    warning logged) if the pool runs out before reaching it.
    """
    if count <= 0:
        raise ValueError("count must be positive")

    max_pool = math.ceil(count * _MAX_POOL_MULTIPLIER)
    seen: dict[str, PhotoResult] = {}
    for provider in providers:
        if len(seen) >= max_pool:
            break
        try:
            results = provider.search(topic, page=1)
        except Exception as exc:
            _log.warning("%s: search failed: %s", type(provider).__name__, exc)
            continue
        for photo in results:
            key = _dedup_key(photo)
            if key and key not in seen:
                seen[key] = photo
            if len(seen) >= max_pool:
                break

    pool = list(seen.values())[:max_pool]
    dest_dir.mkdir(parents=True, exist_ok=True)
    session = build_download_session()
    last_request_at: dict[str, float] = {}

    downloaded: list[str] = []
    for i, photo in enumerate(pool):
        if len(downloaded) >= count:
            break
        ext = Path(urlparse(photo.url).path).suffix or ".jpg"
        dest = str(dest_dir / f"topic_{i:03d}{ext}")
        try:
            download_photo_resilient(session, photo.url, dest, last_request_at)
            downloaded.append(dest)
        except Exception as exc:
            _log.warning("Failed to download photo %s: %s", photo.url, exc)

    if not downloaded:
        raise RuntimeError(f"Could not download any images for topic '{topic}'.")
    if len(downloaded) < count:
        _log.warning("Fetched %d of %d requested images for topic '%s'", len(downloaded), count, topic)

    return downloaded
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_photo_download.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_photo_download.py tests/unit/test_slideshow_photo_download.py
git commit -m "feat(slideshow): add resilient photo downloader and topic-fetch orchestration"
```

---

### Task 5: LLM slideshow script generation

**Files:**
- Create: `docu_studio/slideshow/slideshow_script_gen.py`
- Test: `tests/unit/test_slideshow_script_gen.py`

**Interfaces:**
- Consumes: `LLMProvider` from `docu_studio.adapters.llm.base` (existing — `generate_script(self, topic: str, target_words: int, on_diminishing_returns=None) -> str`).
- Produces: `SLIDESHOW_WPM = 150` (module constant), `target_word_count(image_count: int, seconds_per_image: float = 5.0, wpm: float = SLIDESHOW_WPM) -> int` (raises `ValueError` if `image_count <= 0`), `generate_slideshow_script(topic: str, image_count: int, llm: LLMProvider) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_slideshow_script_gen.py`:

```python
"""Unit tests for Slideshow's LLM narration generation: word-count math and
prompt construction against a mocked LLMProvider."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docu_studio.slideshow.slideshow_script_gen import (
    generate_slideshow_script,
    target_word_count,
)


class TestTargetWordCount:
    def test_default_pace_and_seconds_per_image(self) -> None:
        # 8 images * 5.0s/image = 40s; 40/60 * 150 wpm = 100 words
        assert target_word_count(8) == 100

    def test_custom_seconds_per_image(self) -> None:
        # 6 images * 10.0s/image = 60s; 60/60 * 150 wpm = 150 words
        assert target_word_count(6, seconds_per_image=10.0) == 150

    def test_custom_wpm(self) -> None:
        # 6 images * 10.0s/image = 60s; 60/60 * 120 wpm = 120 words
        assert target_word_count(6, seconds_per_image=10.0, wpm=120) == 120

    def test_zero_image_count_raises(self) -> None:
        with pytest.raises(ValueError):
            target_word_count(0)

    def test_negative_image_count_raises(self) -> None:
        with pytest.raises(ValueError):
            target_word_count(-1)


class TestGenerateSlideshowScript:
    def test_calls_llm_with_target_words_and_topic_prompt(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "  Some narration text.  "

        result = generate_slideshow_script("Mountain landscapes", 8, llm)

        assert result == "Some narration text."
        llm.generate_script.assert_called_once()
        _, kwargs = llm.generate_script.call_args
        assert kwargs["target_words"] == 100
        assert "Mountain landscapes" in kwargs["topic"]

    def test_prompt_requests_even_descriptive_style_not_hook_payoff(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "text"

        generate_slideshow_script("Topic", 6, llm)

        _, kwargs = llm.generate_script.call_args
        prompt = kwargs["topic"]
        assert "descriptive" in prompt.lower()
        assert "no cold-open hook" in prompt.lower()
        assert "no payoff" in prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_script_gen.py -v`
Expected: FAIL / collection error — module doesn't exist yet.

- [ ] **Step 3: Write `docu_studio/slideshow/slideshow_script_gen.py`**

```python
"""LLM-generated narration for Slideshow — even, descriptive pacing, distinct
from docu_studio/shorts/shorts_script_gen.py's punchy hook/payoff style.
Feeds its output into Phase 1's existing script_text -> SlideshowConfig ->
TTS -> split_duration_evenly pipeline unchanged; no sentence-splitting is
needed since that pipeline's segmentation is duration-only, not per-sentence.
"""
from __future__ import annotations

from docu_studio.adapters.llm.base import LLMProvider

SLIDESHOW_WPM = 150
_DEFAULT_SECONDS_PER_IMAGE = 5.0

_SCRIPT_INSTRUCTIONS_TEMPLATE = (
    "You are writing narration for a slideshow video about: {topic}\n\n"
    "STYLE (mandatory):\n"
    "- Even, descriptive, documentary-style narration paced steadily across "
    "the whole script.\n"
    "- No cold-open hook, no rhetorical questions, no payoff/loop structure, "
    "no calls to action.\n"
    "- Plain spoken text only. No markdown, no asterisks, no headers, no "
    "bullet points, no emojis, no quotation marks around the whole thing.\n"
    "- Write numbers the way they should be spoken, e.g. 'ninety percent' "
    "not '90%'.\n"
    "- Target length: approximately {target_words} words.\n\n"
    "Write only the narration text — nothing else."
)


def target_word_count(
    image_count: int,
    seconds_per_image: float = _DEFAULT_SECONDS_PER_IMAGE,
    wpm: float = SLIDESHOW_WPM,
) -> int:
    """Return the target word count for narrating *image_count* images at
    *seconds_per_image* seconds each, spoken at *wpm* words per minute."""
    if image_count <= 0:
        raise ValueError("image_count must be positive")
    duration_seconds = image_count * seconds_per_image
    return round(duration_seconds / 60 * wpm)


def generate_slideshow_script(topic: str, image_count: int, llm: LLMProvider) -> str:
    """Generate even, descriptive slideshow narration for *topic*, sized for
    *image_count* images."""
    target_words = target_word_count(image_count)
    prompt = _SCRIPT_INSTRUCTIONS_TEMPLATE.format(topic=topic, target_words=target_words)
    return llm.generate_script(topic=prompt, target_words=target_words).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_script_gen.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_script_gen.py tests/unit/test_slideshow_script_gen.py
git commit -m "feat(slideshow): add LLM narration generation for topic-based scripts"
```

---

### Task 6: Bridge wiring — fetch_slideshow_images and generate_slideshow_script

**Files:**
- Modify: `docu_studio/gui/bridge.py`

**Interfaces:**
- Consumes: `build_photo_providers` (Task 3), `fetch_topic_images` (Task 4), `generate_slideshow_script` (Task 5), `build_llm` (existing, `docu_studio.adapters.llm.factory`), `key_cache.get` (existing).
- Produces: `Bridge.fetch_slideshow_images(self, topic: str, count: int) -> dict` (`{"ok": True, "paths": [...], "message": "..."}` or `{"ok": False, "error": "..."}`), `Bridge.generate_slideshow_script(self, topic: str, image_count: int) -> dict` (`{"ok": True, "script_text": "..."}` or `{"ok": False, "error": "..."}`).

No dedicated unit test for this task — consistent with the existing convention: `Bridge.start_slideshow_run`/`Bridge.browse_images` have no direct unit tests either, since they require mocking `self._window`/`self._settings`/`key_cache` together, and the one existing bridge test file (`tests/unit/test_bridge_duration.py`) only covers a small extracted pure function. The real logic under test already lives in `fetch_topic_images` (Task 4) and `generate_slideshow_script` (Task 5) — this task is a thin wiring layer. Verification here is: (a) the full test suite stays green (no regressions), (b) manual verification against the real running app happens after Task 7, in the Manual Verification phase.

- [ ] **Step 1: Read the current file to find the exact insertion point**

Open `docu_studio/gui/bridge.py` and find `start_slideshow_run` — it ends with:

```python
        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}

    def cancel_run(self) -> dict:
```

- [ ] **Step 2: Insert the two new methods between `start_slideshow_run` and `cancel_run`**

Replace:

```python
        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}

    def cancel_run(self) -> dict:
```

With:

```python
        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}

    def fetch_slideshow_images(self, topic: str, count: int) -> dict:
        try:
            import tempfile

            from docu_studio.adapters.photos.factory import build_photo_providers
            from docu_studio.slideshow.slideshow_photo_download import fetch_topic_images

            pexels_key = key_cache.get("docu_studio_pexels") or ""
            pixabay_key = key_cache.get("docu_studio_pixabay") or ""
            providers = build_photo_providers(pexels_key, pixabay_key)

            dest_dir = Path(tempfile.mkdtemp(prefix="docu_studio_slideshow_fetch_"))
            paths = fetch_topic_images(topic, int(count), providers, dest_dir)
            message = (
                f"Fetched {len(paths)} of {count} requested images."
                if len(paths) < int(count)
                else f"Fetched {len(paths)} images."
            )
            return {"ok": True, "paths": paths, "message": message}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def generate_slideshow_script(self, topic: str, image_count: int) -> dict:
        try:
            from docu_studio.adapters.llm.factory import build_llm
            from docu_studio.slideshow.slideshow_script_gen import (
                generate_slideshow_script as _generate_slideshow_script,
            )

            s = self._settings
            provider = getattr(s, "llm_provider", "Anthropic")
            model = getattr(s, "llm_model", "claude-sonnet-4-5")
            key_map = {
                "Anthropic": key_cache.get("docu_studio_anthropic"),
                "OpenAI": key_cache.get("docu_studio_openai"),
                "OpenRouter": key_cache.get("docu_studio_openrouter"),
                "Groq": key_cache.get("docu_studio_groq"),
            }
            llm_key = key_map.get(provider, "") or ""
            llm = build_llm(provider, llm_key, model)

            script_text = _generate_slideshow_script(topic, int(image_count), llm)
            return {"ok": True, "script_text": script_text}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def cancel_run(self) -> dict:
```

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `.venv/bin/python -m pytest -q --continue-on-collection-errors`
Expected: same 24 failed / 1 error as the Global Constraints baseline, plus all tests added in Tasks 1-5 passing (478 + 6 + 5 + 3 + 13 + 7 = 512 passed).

- [ ] **Step 4: Commit**

```bash
git add docu_studio/gui/bridge.py
git commit -m "feat(slideshow): wire topic image fetch and LLM script generation into Bridge"
```

---

### Task 7: GUI wiring — topic input, fetch button, thumbnails, Generate button

**Files:**
- Modify: `docu_studio/gui/web/index.html`
- Modify: `docu_studio/gui/web/app.js`
- Modify: `docu_studio/gui/webview_app.py`

**Interfaces:**
- Consumes: `Bridge.fetch_slideshow_images` and `Bridge.generate_slideshow_script` (Task 6), exposed to JS as `window.pywebview.api.fetch_slideshow_images(topic, count)` / `window.pywebview.api.generate_slideshow_script(topic, image_count)`.
- Reuses unchanged: the existing `_slideshowImages` array, `_renderSlideshowImages()`, `_moveSlideshowImage()`, `_removeSlideshowImage()`, `browseSlideshowImages()`, and `startRun()`'s slideshow branch — fetched images are appended into the same array the manual picker fills, so no runner-side or `validate_manual_images` changes are needed.

No automated tests — the existing GUI has no JS test coverage (consistent with Phase 1). Verification is manual, against the real running app, in the Manual Verification phase after this task.

- [ ] **Step 1: Add the topic input + fetch-count stepper + Fetch button to `index.html`**

In `docu_studio/gui/web/index.html`, find:

```html
        <!-- Images (slideshow) -->
        <div id="slideshow-images-row" class="mt-6" style="display:none">
```

Insert immediately before it:

```html
        <!-- Topic-based fetch (slideshow) -->
        <div id="slideshow-topic-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Topic (optional — for fetching images or generating narration)</label>
          <input id="slideshow-topic-input" type="text"
            placeholder="e.g. Mountain landscapes, Vintage cars, Coral reefs"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none placeholder-faint">
          <div class="mt-3 flex items-center gap-3">
            <label class="text-sm text-dim">Images to fetch</label>
            <input id="slideshow-fetch-count" type="number" min="3" max="15" value="8"
              class="w-20 bg-input border border-border rounded-lg px-3 py-2 text-white text-sm text-center focus:border-accent focus:outline-none">
            <button id="slideshow-fetch-btn" onclick="fetchSlideshowTopicImages()" type="button"
              class="px-4 py-2 rounded-lg text-sm font-semibold bg-card border border-border text-dim hover:text-white hover:border-bstrong transition-colors">
              Fetch images
            </button>
          </div>
          <div id="slideshow-fetch-status" class="mt-2 text-xs text-faint"></div>
        </div>

        <!-- Images (slideshow) -->
        <div id="slideshow-images-row" class="mt-6" style="display:none">
```

- [ ] **Step 2: Add the "Generate with LLM" button to the script row in `index.html`**

Find:

```html
        <!-- Script (slideshow) -->
        <div id="slideshow-script-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Narration script</label>
          <textarea id="slideshow-script-input" rows="6"
            placeholder="Paste or write the narration script for your slideshow…"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none placeholder-faint"></textarea>
        </div>
```

Replace with:

```html
        <!-- Script (slideshow) -->
        <div id="slideshow-script-row" class="mt-6" style="display:none">
          <div class="flex items-center justify-between">
            <label class="text-sm font-medium text-dim block">Narration script</label>
            <button id="slideshow-generate-btn" onclick="generateSlideshowScript()" type="button" disabled
              class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-faint cursor-not-allowed transition-colors">
              Generate with LLM
            </button>
          </div>
          <textarea id="slideshow-script-input" rows="6"
            placeholder="Paste or write the narration script for your slideshow…"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none placeholder-faint"></textarea>
        </div>
```

- [ ] **Step 3: Show/hide the new topic row in `startConfig()` in `app.js`**

Find:

```js
  _q('slideshow-images-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-script-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-aspect-row').style.display = mode === 'slideshow' ? '' : 'none';
```

Replace with:

```js
  _q('slideshow-topic-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-images-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-script-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-aspect-row').style.display = mode === 'slideshow' ? '' : 'none';
```

- [ ] **Step 4: Add a thumbnail to each row in `_renderSlideshowImages()` and update the Generate button state**

Find:

```js
function _renderSlideshowImages() {
  const list = _q('slideshow-image-list');
  list.innerHTML = '';
  _slideshowImages.forEach((path, i) => {
    const row = document.createElement('div');
    row.className = 'flex items-center gap-2 bg-input border border-border rounded-lg px-3 py-2 text-sm text-white';

    const nameSpan = document.createElement('span');
```

Replace with:

```js
function _renderSlideshowImages() {
  const list = _q('slideshow-image-list');
  list.innerHTML = '';
  _slideshowImages.forEach((path, i) => {
    const row = document.createElement('div');
    row.className = 'flex items-center gap-2 bg-input border border-border rounded-lg px-3 py-2 text-sm text-white';

    const thumb = document.createElement('img');
    thumb.src = 'file://' + path;
    thumb.className = 'w-10 h-10 object-cover rounded shrink-0';
    thumb.alt = '';
    row.appendChild(thumb);

    const nameSpan = document.createElement('span');
```

Then find the end of the same function:

```js
    list.appendChild(row);
  });
}
```

Replace with:

```js
    list.appendChild(row);
  });
  _updateGenerateButtonState();
}
```

- [ ] **Step 5: Add `fetchSlideshowTopicImages()`, `generateSlideshowScript()`, and `_updateGenerateButtonState()` to `app.js`**

Find:

```js
function _removeSlideshowImage(i) {
  _slideshowImages.splice(i, 1);
  _renderSlideshowImages();
}
```

Insert immediately after it:

```js

async function fetchSlideshowTopicImages() {
  const topic = (_q('slideshow-topic-input')?.value || '').trim();
  if (!topic) {
    _q('slideshow-topic-input').focus();
    _q('slideshow-topic-input').classList.add('border-red-500');
    return;
  }
  const count = Math.min(15, Math.max(3, parseInt(_q('slideshow-fetch-count').value) || 8));
  const btn = _q('slideshow-fetch-btn');
  const status = _q('slideshow-fetch-status');
  btn.disabled = true;
  btn.textContent = 'Fetching…';
  status.textContent = '';
  try {
    const res = await window.pywebview.api.fetch_slideshow_images(topic, count);
    if (res.ok) {
      _slideshowImages = _slideshowImages.concat(res.paths);
      _renderSlideshowImages();
      status.textContent = res.message || '';
    } else {
      status.textContent = 'Failed to fetch images: ' + (res.error || '');
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Fetch images';
  }
}

async function generateSlideshowScript() {
  const topic = (_q('slideshow-topic-input')?.value || '').trim();
  if (!topic) {
    _q('slideshow-topic-input').focus();
    _q('slideshow-topic-input').classList.add('border-red-500');
    return;
  }
  if (_slideshowImages.length === 0) return;
  const btn = _q('slideshow-generate-btn');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  try {
    const res = await window.pywebview.api.generate_slideshow_script(topic, _slideshowImages.length);
    if (res.ok) {
      _q('slideshow-script-input').value = res.script_text;
    } else {
      alert('Failed to generate script: ' + (res.error || ''));
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate with LLM';
  }
}

function _updateGenerateButtonState() {
  const btn = _q('slideshow-generate-btn');
  if (!btn) return;
  const enabled = _slideshowImages.length > 0;
  btn.disabled = !enabled;
  btn.className = enabled
    ? 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-dim hover:text-white hover:border-bstrong transition-colors cursor-pointer'
    : 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-faint cursor-not-allowed transition-colors';
}
```

- [ ] **Step 6: Bump the cache-bust version in `webview_app.py`**

Read the current value first — confirm it is still `?v=11` (from the Global Constraints; re-check the live file since it may have changed):

```bash
grep -n '"?v=' docu_studio/gui/webview_app.py
```

Find:

```python
    the_url = str(WEB_DIR / "index.html") + "?v=11"
```

Replace with the next integer (`?v=12` if the grep confirmed `11`; otherwise increment whatever value the grep showed):

```python
    the_url = str(WEB_DIR / "index.html") + "?v=12"
```

- [ ] **Step 7: Run the full test suite to confirm no regressions**

Run: `.venv/bin/python -m pytest -q --continue-on-collection-errors`
Expected: unchanged from Task 6's count (this task has no Python test changes).

- [ ] **Step 8: Manually verify the GUI renders and the file:// thumbnail approach works**

```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio &
sleep 3
```

Take a screenshot of the running window (per the `run` skill's GUI-driving guidance) after manually clicking through to the Slideshow config screen and adding at least one image via "Choose images…", and confirm:
- The new topic input, fetch-count stepper, and "Fetch images" button render correctly.
- The "Generate with LLM" button renders next to the script label, disabled (greyed out) until an image is present.
- The existing image list row now shows a small thumbnail preview next to the filename (confirms `file://` image loading works — the app already sets `--allow-file-access-from-files --disable-web-security` in `QTWEBENGINE_CHROMIUM_FLAGS`, which is why this is expected to work, but must be visually confirmed, not assumed).

If the thumbnail does not render (blank/broken image icon), that confirms the flagged spec risk — stop and report it rather than proceeding, since the fallback (base64 data URIs) would require a design change to Task 6's `fetch_slideshow_images` return shape.

- [ ] **Step 9: Commit**

```bash
git add docu_studio/gui/web/index.html docu_studio/gui/web/app.js docu_studio/gui/webview_app.py
git commit -m "feat(slideshow): wire topic fetch, LLM script generation, and thumbnails into the GUI"
```

---

## Manual Verification (after all tasks — real runs, not just logs)

Same standard as Phase 1: no mocked network calls in this pass.

1. Confirm Pexels/Pixabay keys and an LLM provider key are configured in Settings (reuse whatever was configured for Documentary/Shorts — no new keys needed).
2. Restart the app (`pkill -f docu_studio 2>/dev/null && DISPLAY=:1 .venv/bin/python -m docu_studio`).
3. Click through to Slideshow → enter a real topic (e.g. "lighthouses") → click "Fetch images" → confirm real photos download and render as thumbnails.
4. Click "Generate with LLM" → confirm real narration text appears in the textarea, roughly sized to the fetched image count, in an even/descriptive tone (not hook/payoff).
5. Click "Start slideshow →" and let the run complete.
6. Extract frames from the output video (same technique as Phase 1) and personally view them to confirm the fetched images render correctly with Ken Burns motion.
7. Note in the final report: this GUI click-through may hit the same synthetic-input limitation documented in the Phase 1 session (X11 input not reaching QtWebEngine content in this sandbox) — if so, fall back to a standalone script calling `Bridge.fetch_slideshow_images` / `Bridge.generate_slideshow_script` / `SlideshowRunner` directly (as Phase 1 did for its end-to-end pipeline verification), and flag GUI click-through as logs-only-verified with a recommendation for the user to confirm manually.

## Self-Review Notes

- **Spec coverage:** §2 (topic-based photo fetch) → Tasks 1-4, 6 (fetch half), 7 (fetch half). §3 (LLM script generation) → Tasks 5, 6 (generate half), 7 (generate half). §4 (error handling) → both bridge methods return `{"ok": False, "error": ...}` on failure (Task 6); partial-fetch messaging (Task 4/6). §5 (testing) → Tasks 1-5 each carry their own test file; Task 6/7 explicitly document why they don't, matching existing convention. §6 (manual verification) → Manual Verification section above. §7 (out of scope) → nothing in this plan adds per-image content alignment, provider-order UI, new API keys, or Phase 3 motion/captions/music.
- **Placeholder scan:** no TBD/TODO; every step has literal code, not a description of code.
- **Type consistency:** `PhotoResult`/`PhotoProvider` (Task 1) used identically in Tasks 2-4; `fetch_topic_images` signature (Task 4) matches its Task 6 call site exactly; `generate_slideshow_script` signature (Task 5) matches its Task 6 call site exactly (including the `topic=`/`target_words=` keyword-argument call into `LLMProvider.generate_script`, which the Task 5 tests assert on directly).
