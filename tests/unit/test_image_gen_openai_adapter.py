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
