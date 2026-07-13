"""Unit tests for clipstory_assembly — ffmpeg and TTS mocked, no real I/O."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.clipstory.clipstory_assembly import ClipStoryFitError, assemble_clip_story
from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig


def _make_config(clips=None) -> ClipStoryConfig:
    clips = clips or [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hello there world.")]
    return ClipStoryConfig(topic="Test", clips=clips)


@pytest.fixture
def mock_ffmpeg():
    with patch("docu_studio.clipstory.clipstory_assembly.ClipStoryFFmpeg") as MockCls:
        instance = MockCls.return_value
        instance.get_duration.return_value = 10.0  # trimmed video == target duration
        yield instance


class TestAssembleClipStoryHappyPath:
    def test_single_clip_within_bounds_no_halt(self, mock_ffmpeg, tmp_path: Path) -> None:
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 10.0]  # trimmed, tempo-audio, (unused 3rd guard)
        tts = MagicMock()
        tts.synthesize.return_value = 10.2  # actual narration duration, close to target
        config = _make_config()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.trim_clip.assert_called_once()
        mock_ffmpeg.normalize_clip.assert_called_once()
        mock_ffmpeg.apply_atempo.assert_called_once()
        mock_ffmpeg.mux_audio_video.assert_called_once()
        mock_ffmpeg.concat_segments.assert_called_once()

    def test_multiple_clips_all_processed_in_order(self, mock_ffmpeg, tmp_path: Path) -> None:
        clips = [
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="First clip narration text."),
            ClipSpec(path="/b.mp4", trim_in=0.0, trim_out=8.0, script_text="Second clip narration text."),
        ]
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 8.0, 8.0]
        tts = MagicMock()
        tts.synthesize.side_effect = [10.0, 8.0]
        config = _make_config(clips)
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        assert mock_ffmpeg.trim_clip.call_count == 2
        assert mock_ffmpeg.mux_audio_video.call_count == 2
        concat_args = mock_ffmpeg.concat_segments.call_args[0][0]
        assert len(concat_args) == 2


class TestAssembleClipStoryLayer3Halt:
    def test_halts_with_numeric_report_when_gap_too_large(self, mock_ffmpeg, tmp_path: Path) -> None:
        mock_ffmpeg.get_duration.return_value = 10.0  # trimmed target duration
        tts = MagicMock()
        tts.synthesize.return_value = 30.0  # wildly over target -> forces halt
        config = _make_config()
        with pytest.raises(ClipStoryFitError, match="target=10.00s"):
            assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.apply_atempo.assert_not_called()
        mock_ffmpeg.concat_segments.assert_not_called()


class TestAssembleClipStoryReconciliation:
    def test_short_narration_gets_padded_before_mux(self, mock_ffmpeg, tmp_path: Path) -> None:
        # trimmed=10.0, raw narration actual=9.0 (within [0.85,1.15] ideal factor 0.9,
        # applied unclamped -> resulting exactly 10.0) then reconciliation get_duration
        # call reports a slightly-short post-atempo duration to force the pad branch.
        mock_ffmpeg.get_duration.side_effect = [10.0, 9.8]
        tts = MagicMock()
        tts.synthesize.return_value = 9.0
        config = _make_config()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.apply_reconciliation.assert_called_once()
        plan = mock_ffmpeg.apply_reconciliation.call_args[0][1]
        assert plan.action == "pad"


class TestAssembleClipStoryCancellation:
    def test_cancel_event_set_before_any_clip_stops_immediately(self, mock_ffmpeg, tmp_path: Path) -> None:
        tts = MagicMock()
        config = _make_config()
        cancel_event = threading.Event()
        cancel_event.set()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4", cancel_event=cancel_event)
        mock_ffmpeg.trim_clip.assert_not_called()
