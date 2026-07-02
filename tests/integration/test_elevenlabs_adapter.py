"""T041: HTTP-mocked integration tests for ElevenLabsAdapter."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.tts.elevenlabs_adapter import ElevenLabsAdapter
from docu_studio.config.settings import Settings


class TestElevenLabsAdapter:
    def _make_adapter(self) -> ElevenLabsAdapter:
        settings = Settings()
        with patch.object(Settings, "get_key", return_value="fake-xi-key"):
            adapter = ElevenLabsAdapter(settings)
        return adapter

    def test_synthesize_calls_api_and_returns_duration(self, tmp_path: Path) -> None:
        output_path = tmp_path / "audio.mp3"
        fake_audio = b"MP3 audio bytes"
        mock_xi = MagicMock()
        mock_xi.text_to_speech.convert.return_value = iter([fake_audio])

        settings = Settings()
        with patch("docu_studio.adapters.tts.elevenlabs_adapter.ElevenLabs", return_value=mock_xi), \
             patch("docu_studio.adapters.tts.elevenlabs_adapter.FFmpegWrapper") as mock_ffmpeg_cls, \
             patch.object(Settings, "get_key", return_value="fake-xi-key"):
            mock_ffmpeg = MagicMock()
            mock_ffmpeg.get_duration.return_value = 8.3
            mock_ffmpeg_cls.return_value = mock_ffmpeg
            adapter = ElevenLabsAdapter(settings)
            duration = adapter.synthesize("Narration text.", str(output_path))

        assert isinstance(duration, float)
        assert duration == 8.3

    def test_synthesize_passes_api_key(self, tmp_path: Path) -> None:
        settings = Settings()
        captured_keys: list[str] = []

        def capture_client(api_key: str, **kwargs: object) -> MagicMock:
            captured_keys.append(api_key)
            m = MagicMock()
            m.text_to_speech.convert.return_value = iter([b"audio"])
            return m

        with patch.object(Settings, "get_key", return_value="my-test-key"), \
             patch("docu_studio.adapters.tts.elevenlabs_adapter.ElevenLabs", side_effect=capture_client), \
             patch("docu_studio.adapters.tts.elevenlabs_adapter.FFmpegWrapper") as mock_ffmpeg_cls:
            mock_ffmpeg = MagicMock()
            mock_ffmpeg.get_duration.return_value = 4.0
            mock_ffmpeg_cls.return_value = mock_ffmpeg
            adapter = ElevenLabsAdapter(settings)
            adapter.synthesize("text", str(tmp_path / "out.mp3"))

        assert "my-test-key" in captured_keys
