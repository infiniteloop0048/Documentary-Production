"""Unit tests for ShortsFFmpeg's new caption/music methods — subprocess mocked,
no real ffmpeg required, matching test_ffmpeg_wrapper.py's convention."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg


@pytest.fixture
def wrapper() -> ShortsFFmpeg:
    with patch("docu_studio.media.ffmpeg_wrapper.imageio_ffmpeg") as mock_ffmpeg_mod:
        mock_ffmpeg_mod.get_ffmpeg_exe.return_value = "/fake/ffmpeg"
        with patch("docu_studio.media.ffmpeg_wrapper.platform_layer") as mock_pl:
            mock_pl.ffprobe_exe.return_value = "/fake/ffprobe"
            return ShortsFFmpeg()


class TestDetectMotionWindow:
    def test_analysis_command_limits_duration_and_fps(self, wrapper: ShortsFFmpeg) -> None:
        # Real-run regression: without a duration/fps cap, motion detection
        # timed out on 10 of 12 clips and silently fell back every time.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.detect_motion_window("/clip.mp4", 45.0, 3.0)

        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "-t" in cmd
        assert cmd[cmd.index("-t") + 1] == "30.0"
        assert cmd.index("-t") < cmd.index("-i")

        vf_value = cmd[cmd.index("-vf") + 1]
        assert "fps=5" in vf_value
        assert "scale=160:-1" in vf_value

        assert kwargs["timeout"] == 20.0

    def test_falls_back_when_no_scene_markers_found(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            start, method = wrapper.detect_motion_window("/clip.mp4", 45.0, 3.0)
        assert method == "fallback"
        assert start == min(round(45.0 * 0.4, 2), 45.0 - 3.0)

    def test_falls_back_on_timeout(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=20.0)):
            start, method = wrapper.detect_motion_window("/clip.mp4", 45.0, 3.0)
        assert method == "fallback"
        assert start == min(round(45.0 * 0.4, 2), 45.0 - 3.0)


class TestBurnCaptions:
    def test_filter_value_uses_bare_filename_never_a_colon_or_path_separator(
        self, wrapper: ShortsFFmpeg
    ) -> None:
        # A colon in the directory (e.g. a Windows drive letter "C:\...") is
        # exactly the case that broke ffmpeg's -vf filtergraph parser and
        # avio's protocol-scheme detection — see shorts_ffmpeg.py's docstring
        # on burn_captions for why cwd + bare filename is used instead.
        ass_path = "/some/output/C:weird/video/captions.ass"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions("/some/output/video/short_concat.mp4", ass_path, "/some/output/video/captioned.mp4")

        args = mock_run.call_args[0][0]
        vf_index = args.index("-vf")
        vf_value = args[vf_index + 1]
        assert vf_value == "subtitles=captions.ass"
        assert ":" not in vf_value.split("=", 1)[1]

    def test_runs_with_cwd_set_to_ass_file_directory(self, wrapper: ShortsFFmpeg) -> None:
        ass_path = "/some/output/video/captions.ass"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions("/in.mp4", ass_path, "/out.mp4")
        assert mock_run.call_args.kwargs["cwd"] == "/some/output/video"

    def test_input_and_output_paths_are_absolute_argv_values(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions("in.mp4", "/some/dir/captions.ass", "out.mp4")
        args = mock_run.call_args[0][0]
        assert args[args.index("-i") + 1].endswith("in.mp4")
        assert args[-1].endswith("out.mp4")


class TestMixMusicBed:
    def test_calls_ffmpeg_with_looped_music_input_and_aout_map(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mix_music_bed("/voice.mp3", "/music.mp3", 30.0, "/mixed.m4a")
        args = mock_run.call_args[0][0]
        assert "-stream_loop" in args
        assert "-1" in args
        assert "/music.mp3" in args
        assert "[aout]" in args
        assert "/mixed.m4a" in args
