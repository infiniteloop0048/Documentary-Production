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


class TestApplyKenBurns:
    def test_upscales_before_zoompan_with_lanczos(self, wrapper: ShortsFFmpeg) -> None:
        # Real-run regression: zoompan crops on integer pixel coordinates at input
        # resolution, so without a pre-zoompan upscale each zoom increment lands on
        # the same source pixel for several output frames — visible stepping.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns("/in.mp4", "/out.mp4", 3.0, "in", False)

        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert "scale=4320:-2" in vf
        assert "lanczos" in vf
        assert vf.index("scale=") < vf.index("zoompan=")

    def test_zoom_expression_is_frame_linear_not_accumulating(self, wrapper: ShortsFFmpeg) -> None:
        # The common 'zoom+0.001' accumulator pattern drifts and stutters — z must
        # be a pure function of the output frame number ('on') instead.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns("/in.mp4", "/out.mp4", 3.0, "in", False)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "zoom+" not in vf
        assert "on/" in vf

    def test_zoom_out_direction_is_also_frame_linear(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns("/in.mp4", "/out.mp4", 3.0, "out", False)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "zoom+" not in vf
        assert "zoom-" not in vf

    def test_pan_expression_is_frame_indexed(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns("/in.mp4", "/out.mp4", 3.0, "in", True)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "x='" in vf

    def test_frame_count_and_fps_match_duration(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns("/in.mp4", "/out.mp4", 3.0, "in", False)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "d=90" in vf  # 3.0s * 30fps
        assert "fps=30" in vf
        assert "s=1080x1920" in vf


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


class TestApplySpeedRamp:
    def test_uses_setpts_with_the_given_factor(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_speed_ramp("/in.mp4", "/out.mp4", 1.35)
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert vf == "setpts=PTS/1.35"

    def test_strips_audio_stream(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_speed_ramp("/in.mp4", "/out.mp4", 1.25)
        args = mock_run.call_args[0][0]
        assert "-an" in args

    def test_input_and_output_paths_are_argv_values(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_speed_ramp("/clip_in.mp4", "/clip_out.mp4", 1.5)
        args = mock_run.call_args[0][0]
        assert args[args.index("-i") + 1] == "/clip_in.mp4"
        assert args[-1] == "/clip_out.mp4"


class TestGeneratePunchCard:
    def test_base_card_uses_lavfi_color_source_and_drawtext(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card("/out/card.mp4", "90 PERCENT", 1.0)
        first_cmd = mock_run.call_args_list[0][0][0]
        assert "-f" in first_cmd and "lavfi" in first_cmd
        vf = first_cmd[first_cmd.index("-vf") + 1]
        assert "drawtext=" in vf
        assert "90 PERCENT" in vf

    def test_scale_in_pass_uses_zoompan_on_upscaled_base(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card("/out/card.mp4", "90 PERCENT", 1.0)
        second_cmd = mock_run.call_args_list[1][0][0]
        vf = second_cmd[second_cmd.index("-vf") + 1]
        assert "zoompan=" in vf
        assert "scale=4320:-2" in vf
        assert "lanczos" in vf
        assert second_cmd[second_cmd.index("-i") + 1] == "/out/card.mp4.base.mp4"

    def test_two_ffmpeg_calls_are_made(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card("/out/card.mp4", "one million", 1.2)
        assert mock_run.call_count == 2

    def test_frame_count_matches_duration(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card("/out/card.mp4", "text", 1.2)
        second_cmd = mock_run.call_args_list[1][0][0]
        vf = second_cmd[second_cmd.index("-vf") + 1]
        assert "d=36" in vf  # 1.2s * 30fps

    def test_single_quotes_in_text_are_escaped(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card("/out/card.mp4", "IT'S HUGE", 1.0)
        first_cmd = mock_run.call_args_list[0][0][0]
        vf = first_cmd[first_cmd.index("-vf") + 1]
        assert "IT\\'S HUGE" in vf
