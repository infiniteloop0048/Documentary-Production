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
