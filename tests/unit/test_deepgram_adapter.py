"""Unit tests for DeepgramAdapter — synthesize() call construction and the
retry/backoff wrapper (mirrors ElevenLabsAdapter's @retry pattern, per
Deepgram's own documented recommendation of exponential backoff for
transient/rate-limit failures). requests.post is mocked throughout; no real
network calls happen in this suite.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from docu_studio.adapters.tts.deepgram_adapter import DeepgramAdapter


@pytest.fixture
def adapter() -> DeepgramAdapter:
    return DeepgramAdapter(api_key="fake-dg-key", voice="aura-asteria-en")


class TestSynthesize:
    def test_calls_api_with_key_and_voice_and_returns_duration(
        self, adapter: DeepgramAdapter, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "out.mp3"
        mock_resp = MagicMock()
        mock_resp.content = b"fake mp3 bytes"
        mock_resp.raise_for_status.return_value = None

        with patch("docu_studio.adapters.tts.deepgram_adapter.requests.post", return_value=mock_resp) as mock_post, \
             patch.object(adapter._ffmpeg, "get_duration", return_value=5.5):
            duration = adapter.synthesize("Narration text.", str(output_path))

        assert duration == 5.5
        assert output_path.read_bytes() == b"fake mp3 bytes"
        call_kwargs = mock_post.call_args
        assert "aura-asteria-en" in call_kwargs.args[0]
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Token fake-dg-key"
        assert call_kwargs.kwargs["json"] == {"text": "Narration text."}


class TestRetryBehavior:
    """New behavior: DeepgramAdapter previously had no retry at all — a gap
    that matters more once per-sentence synthesis means N independent calls
    per video instead of 1 (Task 4 Section 1)."""

    def test_succeeds_after_transient_failure(self, adapter: DeepgramAdapter, tmp_path: Path) -> None:
        calls = {"n": 0}
        mock_resp = MagicMock()
        mock_resp.content = b"fake mp3 bytes"
        mock_resp.raise_for_status.return_value = None

        def flaky_post(*args: object, **kwargs: object) -> MagicMock:
            calls["n"] += 1
            if calls["n"] < 2:
                raise requests.exceptions.ConnectionError("reset")
            return mock_resp

        with patch("docu_studio.adapters.tts.deepgram_adapter.requests.post", side_effect=flaky_post), \
             patch.object(adapter._ffmpeg, "get_duration", return_value=3.5), \
             patch("time.sleep"):
            duration = adapter.synthesize("some text", str(tmp_path / "out.mp3"))

        assert duration == 3.5
        assert calls["n"] == 2

    def test_retries_on_429_rate_limit_response(self, adapter: DeepgramAdapter, tmp_path: Path) -> None:
        calls = {"n": 0}
        rate_limited_resp = MagicMock()
        rate_limited_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Too Many Requests")
        ok_resp = MagicMock()
        ok_resp.content = b"fake mp3 bytes"
        ok_resp.raise_for_status.return_value = None

        def flaky_post(*args: object, **kwargs: object) -> MagicMock:
            calls["n"] += 1
            return rate_limited_resp if calls["n"] < 2 else ok_resp

        with patch("docu_studio.adapters.tts.deepgram_adapter.requests.post", side_effect=flaky_post), \
             patch.object(adapter._ffmpeg, "get_duration", return_value=2.0), \
             patch("time.sleep"):
            duration = adapter.synthesize("some text", str(tmp_path / "out.mp3"))

        assert duration == 2.0
        assert calls["n"] == 2

    def test_raises_after_exhausting_all_retries(self, adapter: DeepgramAdapter, tmp_path: Path) -> None:
        with patch(
            "docu_studio.adapters.tts.deepgram_adapter.requests.post",
            side_effect=requests.exceptions.ConnectionError("still down"),
        ), patch("time.sleep"):
            with pytest.raises(requests.exceptions.ConnectionError, match="still down"):
                adapter.synthesize("some text", str(tmp_path / "out.mp3"))

    def test_uses_exponential_backoff_with_three_attempts(
        self, adapter: DeepgramAdapter, tmp_path: Path
    ) -> None:
        """Mirrors ElevenLabsAdapter's @retry(max_attempts=3, backoff_factor=2.0,
        base_delay=1.0) exactly — Deepgram's own docs recommend exponential
        backoff and don't specify a Retry-After header to honor instead, so
        there's no evidence justifying different parameters from ElevenLabs."""
        sleep_calls: list[float] = []

        with patch(
            "docu_studio.adapters.tts.deepgram_adapter.requests.post",
            side_effect=requests.exceptions.ConnectionError("down"),
        ), patch("time.sleep", side_effect=sleep_calls.append):
            with pytest.raises(requests.exceptions.ConnectionError):
                adapter.synthesize("some text", str(tmp_path / "out.mp3"))

        assert sleep_calls == [1.0, 2.0]
