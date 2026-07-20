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
