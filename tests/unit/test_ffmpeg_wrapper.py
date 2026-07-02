"""Unit tests for FFmpegWrapper — subprocess mocked; no real FFmpeg required."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.media.ffmpeg_wrapper import FFmpegError, FFmpegWrapper


@pytest.fixture
def wrapper() -> FFmpegWrapper:
    with patch("docu_studio.media.ffmpeg_wrapper.imageio_ffmpeg") as mock_ffmpeg_mod:
        mock_ffmpeg_mod.get_ffmpeg_exe.return_value = "/fake/ffmpeg"
        with patch("docu_studio.media.ffmpeg_wrapper.platform_layer") as mock_pl:
            mock_pl.ffprobe_exe.return_value = "/fake/ffprobe"
            return FFmpegWrapper()


class TestGetDuration:
    def test_returns_float_from_ffprobe_output(self, wrapper: FFmpegWrapper) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="12.345\n", stderr="")
            result = wrapper.get_duration("/some/file.mp3")
        assert result == pytest.approx(12.345)
        args = mock_run.call_args[0][0]
        assert "/fake/ffprobe" in args
        assert "/some/file.mp3" in args

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: FFmpegWrapper) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
            with pytest.raises(FFmpegError):
                wrapper.get_duration("/bad/file.mp3")


class TestTrimClip:
    def test_calls_ffmpeg_with_correct_args(self, wrapper: FFmpegWrapper, tmp_path) -> None:
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.trim_clip("/in.mp4", 0.0, 10.5, out)
        args = mock_run.call_args[0][0]
        assert "/fake/ffmpeg" in args
        assert "-ss" in args
        assert "-t" in args
        assert out in args

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: FFmpegWrapper, tmp_path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="bad")
            with pytest.raises(FFmpegError):
                wrapper.trim_clip("/in.mp4", 0.0, 5.0, str(tmp_path / "out.mp4"))


class TestConcatClips:
    def test_calls_ffmpeg_concat_filter(self, wrapper: FFmpegWrapper, tmp_path) -> None:
        out = str(tmp_path / "concat.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_clips(["/a.mp4", "/b.mp4"], out)
        args = mock_run.call_args[0][0]
        assert "/fake/ffmpeg" in args
        assert out in args

    def test_raises_on_failure(self, wrapper: FFmpegWrapper, tmp_path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fail")
            with pytest.raises(FFmpegError):
                wrapper.concat_clips(["/a.mp4"], str(tmp_path / "out.mp4"))


class TestMuxAudioVideo:
    def test_calls_ffmpeg_with_audio_and_video(self, wrapper: FFmpegWrapper, tmp_path) -> None:
        out = str(tmp_path / "muxed.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mux_audio_video("/video.mp4", "/audio.mp3", out)
        args = mock_run.call_args[0][0]
        assert "/video.mp4" in args
        assert "/audio.mp3" in args
        assert out in args

    def test_raises_on_failure(self, wrapper: FFmpegWrapper, tmp_path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="err")
            with pytest.raises(FFmpegError):
                wrapper.mux_audio_video("/v.mp4", "/a.mp3", str(tmp_path / "out.mp4"))

    def test_explicitly_maps_video_from_first_input_only(
        self, wrapper: FFmpegWrapper, tmp_path
    ) -> None:
        """Regression test: without -map, ffmpeg auto-selects streams and can pull the
        source clip's own audio track instead of the TTS track when the clip has audio.
        """
        out = str(tmp_path / "muxed.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mux_audio_video("/video.mp4", "/audio.mp3", out)
        args = mock_run.call_args[0][0]
        map_values = [args[i + 1] for i, a in enumerate(args) if a == "-map"]
        assert "0:v:0" in map_values, f"expected video mapped from input 0, got -map values {map_values}"

    def test_explicitly_maps_audio_from_second_input_only(
        self, wrapper: FFmpegWrapper, tmp_path
    ) -> None:
        out = str(tmp_path / "muxed.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mux_audio_video("/video.mp4", "/audio.mp3", out)
        args = mock_run.call_args[0][0]
        map_values = [args[i + 1] for i, a in enumerate(args) if a == "-map"]
        assert "1:a:0" in map_values, f"expected audio mapped from input 1 (TTS), got -map values {map_values}"


class TestHasAudioStream:
    def test_returns_true_when_clip_has_audio_stream(self, wrapper: FFmpegWrapper) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="0\n", stderr="")
            assert wrapper.has_audio_stream("/clip_with_audio.mp4") is True

    def test_returns_false_when_clip_has_no_audio_stream(self, wrapper: FFmpegWrapper) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            assert wrapper.has_audio_stream("/clip_silent.mp4") is False

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: FFmpegWrapper) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="bad probe")
            with pytest.raises(FFmpegError):
                wrapper.has_audio_stream("/bad.mp4")
