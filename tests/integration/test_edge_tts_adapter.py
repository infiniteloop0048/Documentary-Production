"""T040: Mocked integration tests for EdgeTTSAdapter."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docu_studio.adapters.tts.edge_tts_adapter import EdgeTTSAdapter


class TestEdgeTTSAdapter:
    def _make_adapter(self) -> EdgeTTSAdapter:
        return EdgeTTSAdapter()

    def test_synthesize_writes_file_and_returns_duration(self, tmp_path: Path) -> None:
        output_path = tmp_path / "audio.mp3"

        async def fake_communicate_save(path: str) -> None:
            Path(path).write_bytes(b"fake audio data")

        mock_communicate = MagicMock()
        mock_communicate.return_value.save = AsyncMock(side_effect=fake_communicate_save)

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 12.5

        with patch("docu_studio.adapters.tts.edge_tts_adapter.FFmpegWrapper", return_value=mock_ffmpeg), \
             patch("edge_tts.Communicate", mock_communicate):
            adapter = EdgeTTSAdapter()
            duration = adapter.synthesize("Hello world.", str(output_path))

        assert isinstance(duration, float)
        assert duration == 12.5

    def test_synthesize_calls_communicate_with_text(self, tmp_path: Path) -> None:
        output_path = tmp_path / "audio.mp3"
        captured_text: list[str] = []

        async def fake_save(path: str) -> None:
            Path(path).write_bytes(b"audio")

        def capture_communicate(text: str, voice: str = "", **kwargs: object) -> MagicMock:
            captured_text.append(text)
            m = MagicMock()
            m.save = AsyncMock(side_effect=fake_save)
            return m

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 5.0

        with patch("docu_studio.adapters.tts.edge_tts_adapter.FFmpegWrapper", return_value=mock_ffmpeg), \
             patch("edge_tts.Communicate", side_effect=capture_communicate):
            adapter = EdgeTTSAdapter()
            adapter.synthesize("Test narration.", str(output_path))

        assert captured_text[0] == "Test narration."
