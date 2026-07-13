"""Unit tests for clipstory_assembly — ffmpeg and TTS mocked, no real I/O."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.clipstory.clipstory_assembly import (
    ClipStoryFitError,
    ClipStoryTransitionError,
    assemble_clip_story,
)
from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig


def _make_config(clips=None) -> ClipStoryConfig:
    clips = clips or [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hello there world.")]
    return ClipStoryConfig(topic="Test", clips=clips)


def _touch_last_arg(*args, **kwargs) -> None:
    """Side effect for concat_segments/concat_segments_with_xfade mocks: the real
    ffmpeg call would write a file at its output-path argument, and the code under
    test now does a real shutil.copy from that path when no music is mixed — so the
    mock needs to actually leave a file behind for that copy to succeed."""
    Path(args[-1]).touch()


@pytest.fixture
def mock_ffmpeg():
    with patch("docu_studio.clipstory.clipstory_assembly.ClipStoryFFmpeg") as MockCls:
        instance = MockCls.return_value
        instance.get_duration.return_value = 10.0  # trimmed video == target duration
        instance.concat_segments.side_effect = _touch_last_arg
        instance.concat_segments_with_xfade.side_effect = _touch_last_arg
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


class TestAssembleClipStoryCaptions:
    def test_captions_disabled_by_default_skips_burn_captions(self, mock_ffmpeg, tmp_path: Path) -> None:
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 10.0]
        tts = MagicMock()
        tts.synthesize.return_value = 10.2
        config = _make_config()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.burn_captions.assert_not_called()
        mock_ffmpeg.concat_segments.assert_called_once()
        mock_ffmpeg.concat_segments_with_xfade.assert_not_called()
        mock_ffmpeg.mix_music_bed.assert_not_called()

    def test_captions_enabled_burns_per_clip_with_clip_local_duration(
        self, mock_ffmpeg, tmp_path: Path
    ) -> None:
        clips = [
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="First clip narration text."),
            ClipSpec(path="/b.mp4", trim_in=0.0, trim_out=6.0, script_text="Second one shorter text here."),
        ]
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 6.0, 6.0]
        tts = MagicMock()
        tts.synthesize.side_effect = [10.0, 6.0]
        config = _make_config(clips)
        config.captions = True

        with patch("docu_studio.common.captions.estimate_word_timestamps") as mock_estimate, \
             patch("docu_studio.common.captions.write_ass_file") as mock_write_ass:
            mock_estimate.return_value = []
            assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")

        assert mock_estimate.call_count == 2
        first_call_args = mock_estimate.call_args_list[0][0]
        second_call_args = mock_estimate.call_args_list[1][0]
        assert first_call_args == ("First clip narration text.", 10.0)
        assert second_call_args == ("Second one shorter text here.", 6.0)

        assert mock_write_ass.call_count == 2
        assert mock_write_ass.call_args_list[0][0][4] == 10.0
        assert mock_write_ass.call_args_list[1][0][4] == 6.0

        assert mock_ffmpeg.burn_captions.call_count == 2


class TestAssembleClipStoryCrossfade:
    def test_crossfade_enabled_with_valid_durations_calls_xfade_concat(
        self, mock_ffmpeg, tmp_path: Path
    ) -> None:
        clips = [
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="First clip narration text."),
            ClipSpec(path="/b.mp4", trim_in=0.0, trim_out=8.0, script_text="Second clip narration text."),
        ]
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 8.0, 8.0]
        tts = MagicMock()
        tts.synthesize.side_effect = [10.0, 8.0]
        config = _make_config(clips)
        config.transition = "crossfade"
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.concat_segments.assert_not_called()
        mock_ffmpeg.concat_segments_with_xfade.assert_called_once()
        durations_arg = mock_ffmpeg.concat_segments_with_xfade.call_args[0][1]
        assert durations_arg == [10.0, 8.0]

    def test_crossfade_with_clip_too_short_halts_before_any_concat_call(
        self, mock_ffmpeg, tmp_path: Path
    ) -> None:
        clips = [
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=0.3, script_text="Hi there."),
            ClipSpec(path="/b.mp4", trim_in=0.0, trim_out=5.0, script_text="Second clip text here now."),
        ]
        mock_ffmpeg.get_duration.side_effect = [0.3, 0.3, 5.0, 5.0]
        tts = MagicMock()
        tts.synthesize.side_effect = [0.3, 5.0]
        config = _make_config(clips)
        config.transition = "crossfade"
        with pytest.raises(ClipStoryTransitionError):
            assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.concat_segments.assert_not_called()
        mock_ffmpeg.concat_segments_with_xfade.assert_not_called()

    def test_crossfade_with_exactly_one_clip_falls_back_to_hard_cut(
        self, mock_ffmpeg, tmp_path: Path
    ) -> None:
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 10.0]
        tts = MagicMock()
        tts.synthesize.return_value = 10.2
        config = _make_config()
        config.transition = "crossfade"
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4")
        mock_ffmpeg.concat_segments.assert_called_once()
        mock_ffmpeg.concat_segments_with_xfade.assert_not_called()


class TestAssembleClipStoryMusic:
    def test_music_enabled_with_resolved_track_mixes_and_remuxes(
        self, mock_ffmpeg, tmp_path: Path
    ) -> None:
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 15.0]
        tts = MagicMock()
        tts.synthesize.return_value = 10.2
        config = _make_config()
        assemble_clip_story(
            config, tts, tmp_path, tmp_path / "out.mp4", music_path="/music/bed.mp3"
        )
        assembled_path = str(tmp_path / "clipstory_assembled.mp4")
        mixed_audio_path = str(tmp_path / "clipstory_music_mixed.m4a")
        mock_ffmpeg.mix_music_bed.assert_called_once_with(
            assembled_path, "/music/bed.mp3", 15.0, mixed_audio_path
        )
        assert mock_ffmpeg.mux_audio_video.call_count == 2
        final_mux_args = mock_ffmpeg.mux_audio_video.call_args_list[-1][0]
        assert final_mux_args == (assembled_path, mixed_audio_path, str(tmp_path / "out.mp4"))

    def test_music_enabled_with_no_resolved_track_skips_mix(
        self, mock_ffmpeg, tmp_path: Path
    ) -> None:
        mock_ffmpeg.get_duration.side_effect = [10.0, 10.0, 10.0]
        tts = MagicMock()
        tts.synthesize.return_value = 10.2
        config = _make_config()
        assemble_clip_story(config, tts, tmp_path, tmp_path / "out.mp4", music_path=None)
        mock_ffmpeg.mix_music_bed.assert_not_called()
        assert mock_ffmpeg.mux_audio_video.call_count == 1
        assert (tmp_path / "out.mp4").exists()
