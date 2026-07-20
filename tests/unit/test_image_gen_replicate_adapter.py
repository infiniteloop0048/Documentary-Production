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
