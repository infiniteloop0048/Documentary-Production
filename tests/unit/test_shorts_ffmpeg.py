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

    def test_logs_tier_chain_version_marker_unconditionally(
        self, wrapper: ShortsFFmpeg, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Real-run regression: a run well after the tiered-chain fix landed on
        # disk still showed zero diagnostic reasoning and 100% dumb fallback
        # in shorts_log.txt, because a long-running app process keeps whatever
        # module code was imported at startup — editing the .py file has no
        # effect until the process restarts. This marker line lets any run's
        # log prove which chain actually executed, so that ambiguity doesn't
        # require re-deriving it from message-format archaeology again. Must
        # fire even on the earliest possible return (usable <= 0).
        with caplog.at_level("INFO"):
            wrapper.detect_motion_window("/clip.mp4", clip_duration=2.0, window=5.0)
        messages = [r.message for r in caplog.records]
        assert any("tier-chain=scene-change/motion-energy/fallback" in m for m in messages)

    def test_falls_through_to_motion_energy_when_scene_change_finds_nothing(
        self, wrapper: ShortsFFmpeg, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Real-run regression: 9 of 11 real segments fell back with NO logged
        # reason — turned out to be clips with continuous smooth motion (slow
        # drone shots, calm scenery) that legitimately never cross the 0.1
        # scene-change threshold. Motion-energy sampling should catch these.
        scene_result = MagicMock(returncode=0, stdout="", stderr="")
        energy_stderr = (
            "pts_time:0\nlavfi.signalstats.YDIF=1.0\n"
            "pts_time:5\nlavfi.signalstats.YDIF=9.0\n"
        )
        energy_result = MagicMock(returncode=0, stdout="", stderr=energy_stderr)
        with patch("subprocess.run", side_effect=[scene_result, energy_result]):
            with caplog.at_level("INFO"):
                start, method = wrapper.detect_motion_window("/clip.mp4", 20.0, 3.0)
        assert method == "motion_energy"
        assert start == 5.0
        messages = [r.message for r in caplog.records]
        assert any("zero scene-change markers" in m for m in messages)
        assert any("motion-energy sampling" in m for m in messages)

    def test_scene_change_timeout_still_tries_motion_energy(
        self, wrapper: ShortsFFmpeg
    ) -> None:
        energy_result = MagicMock(
            returncode=0, stdout="", stderr="pts_time:5\nlavfi.signalstats.YDIF=9.0\n",
        )
        with patch(
            "subprocess.run",
            side_effect=[subprocess.TimeoutExpired(cmd="ffmpeg", timeout=20.0), energy_result],
        ):
            start, method = wrapper.detect_motion_window("/clip.mp4", 20.0, 3.0)
        assert method == "motion_energy"
        assert start == 5.0

    def test_falls_through_all_three_tiers_to_dumb_fallback(
        self, wrapper: ShortsFFmpeg, caplog: pytest.LogCaptureFixture
    ) -> None:
        empty_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", side_effect=[empty_result, empty_result]):
            with caplog.at_level("INFO"):
                start, method = wrapper.detect_motion_window("/clip.mp4", 45.0, 3.0)
        assert method == "fallback"
        assert start == min(round(45.0 * 0.4, 2), 45.0 - 3.0)
        messages = [r.message for r in caplog.records]
        assert any("zero scene-change markers" in m for m in messages)
        assert any("motion-energy sampling also found nothing" in m for m in messages)

    def test_motion_energy_timeout_falls_to_dumb_fallback(self, wrapper: ShortsFFmpeg) -> None:
        empty_scene = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "subprocess.run",
            side_effect=[empty_scene, subprocess.TimeoutExpired(cmd="ffmpeg", timeout=20.0)],
        ):
            start, method = wrapper.detect_motion_window("/clip.mp4", 45.0, 3.0)
        assert method == "fallback"
        assert start == min(round(45.0 * 0.4, 2), 45.0 - 3.0)


class TestBestEnergyWindow:
    def test_picks_highest_average_energy_window(self) -> None:
        stderr = (
            "pts_time:0\nlavfi.signalstats.YDIF=1.0\n"
            "pts_time:0.5\nlavfi.signalstats.YDIF=1.0\n"
            "pts_time:1\nlavfi.signalstats.YDIF=1.0\n"
            "pts_time:5\nlavfi.signalstats.YDIF=9.0\n"
            "pts_time:5.5\nlavfi.signalstats.YDIF=9.0\n"
            "pts_time:6\nlavfi.signalstats.YDIF=9.0\n"
        )
        start = ShortsFFmpeg._best_energy_window(stderr, usable=6.0, window=1.0)
        assert start == 5.0

    def test_returns_none_when_no_samples_found(self) -> None:
        assert ShortsFFmpeg._best_energy_window("", usable=10.0, window=1.0) is None

    def test_ignores_samples_outside_usable_range(self) -> None:
        stderr = "pts_time:20\nlavfi.signalstats.YDIF=99.0\n"
        assert ShortsFFmpeg._best_energy_window(stderr, usable=5.0, window=1.0) is None

    def test_parses_real_ffmpeg_metadata_print_format_with_filter_prefix(self) -> None:
        # Real ffmpeg prepends "[Parsed_metadata_N @ 0x...]" to every printed
        # line, not just a bare "pts_time:"/"lavfi..." pair.
        stderr = (
            "[Parsed_metadata_3 @ 0x1] frame:0   pts:0   pts_time:0\n"
            "[Parsed_metadata_3 @ 0x1] lavfi.signalstats.YDIF=1.0\n"
            "[Parsed_metadata_3 @ 0x1] frame:25  pts:25  pts_time:5\n"
            "[Parsed_metadata_3 @ 0x1] lavfi.signalstats.YDIF=9.0\n"
        )
        start = ShortsFFmpeg._best_energy_window(stderr, usable=5.0, window=1.0)
        assert start == 5.0


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

    def test_filter_chain_ends_with_setsar_and_format(self, wrapper: ShortsFFmpeg) -> None:
        # Ken Burns' 4x lanczos upscale + zoompan is the step that produced
        # the drifted SAR (e.g. 17485:17484) in production — see the module
        # docstring on docu_studio.common.ffmpeg_finalize.finalize_filter.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns("/in.mp4", "/out.mp4", 3.0, "in", False)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf.endswith(",setsar=1,format=yuv420p")


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

    def test_omitted_volume_defaults_to_ducking_module_baseline(self, wrapper: ShortsFFmpeg) -> None:
        from docu_studio.common.audio_ducking import MUSIC_BASELINE_DB

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mix_music_bed("/voice.mp3", "/music.mp3", 30.0, "/mixed.m4a")
        filter_complex = mock_run.call_args[0][0][
            mock_run.call_args[0][0].index("-filter_complex") + 1
        ]
        assert f"volume={MUSIC_BASELINE_DB}dB" in filter_complex

    def test_custom_volume_is_passed_through_to_filtergraph(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mix_music_bed("/voice.mp3", "/music.mp3", 30.0, "/mixed.m4a", -8.0)
        filter_complex = mock_run.call_args[0][0][
            mock_run.call_args[0][0].index("-filter_complex") + 1
        ]
        assert "volume=-8.0dB" in filter_complex


class TestApplySpeedRamp:
    def test_uses_setpts_with_the_given_factor(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_speed_ramp("/in.mp4", "/out.mp4", 1.35)
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert vf == "setpts=PTS/1.35,setsar=1,format=yuv420p"

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


class TestVerticalConvert:
    def test_center_crop_filter_chain_ends_with_setsar_and_format(self, wrapper: ShortsFFmpeg) -> None:
        # vertical_convert's force_original_aspect_ratio scale+crop is the other
        # chained-scale step implicated in the SAR-drift bug.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.vertical_convert("/in.mp4", "/out.mp4", "center_crop")
        args = mock_run.call_args[0][0]
        filter_complex = args[args.index("-filter_complex") + 1]
        assert ",setsar=1,format=yuv420p[vout]" in filter_complex

    def test_blur_pad_filter_chain_ends_with_setsar_and_format(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.vertical_convert("/in.mp4", "/out.mp4", "blur_pad")
        args = mock_run.call_args[0][0]
        filter_complex = args[args.index("-filter_complex") + 1]
        assert ",setsar=1,format=yuv420p[vout]" in filter_complex


class TestGeneratePunchCard:
    def test_uses_lavfi_color_source_with_theme_background(
        self, wrapper: ShortsFFmpeg, tmp_path
    ) -> None:
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "90 PERCENT", 1.0)
        cmd = mock_run.call_args[0][0]
        assert "-f" in cmd and "lavfi" in cmd
        source = cmd[cmd.index("-i") + 1]
        assert source.startswith("color=c=0x141620:")

    def test_filter_value_uses_bare_ass_filename_never_a_path(
        self, wrapper: ShortsFFmpeg, tmp_path
    ) -> None:
        # Mirrors TestBurnCaptions::test_filter_value_uses_bare_filename_never_a_colon_or_path_separator —
        # the subtitles= filter must reference the .ass file's bare name only.
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "90 PERCENT", 1.0)
        cmd = mock_run.call_args[0][0]
        vf = cmd[cmd.index("-vf") + 1]
        assert vf == "subtitles=card.mp4.card.ass,setsar=1,format=yuv420p"
        assert ":" not in vf.split("=", 1)[1].split(",")[0]

    def test_cwd_matches_output_path_directory(self, wrapper: ShortsFFmpeg, tmp_path) -> None:
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "90 PERCENT", 1.0)
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_ass_file_contains_text_center_alignment_and_scale_transform(
        self, wrapper: ShortsFFmpeg, tmp_path
    ) -> None:
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "90 PERCENT", 1.0)
        ass_content = (tmp_path / "card.mp4.card.ass").read_text(encoding="utf-8")
        assert "90 PERCENT" in ass_content
        style_line = next(line for line in ass_content.splitlines() if line.startswith("Style:"))
        fields = style_line.split(",")
        assert fields[-5] == "5"  # Alignment field, center (MarginL/R/V + Encoding follow)
        dialogue_line = next(line for line in ass_content.splitlines() if line.startswith("Dialogue:"))
        assert "\\t(" in dialogue_line

    def test_single_ffmpeg_call_is_made(self, wrapper: ShortsFFmpeg, tmp_path) -> None:
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "one million", 1.2)
        assert mock_run.call_count == 1

    def test_apostrophe_and_colon_appear_verbatim_unescaped(
        self, wrapper: ShortsFFmpeg, tmp_path
    ) -> None:
        # Regression guard for the drawtext corruption bug: ASS's Text field
        # is the last comma-separated field, so it needs no colon/quote
        # escaping — unlike drawtext, which silently dropped the apostrophe.
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "IT'S 50:50 HUGE", 1.0)
        ass_content = (tmp_path / "card.mp4.card.ass").read_text(encoding="utf-8")
        dialogue_line = next(line for line in ass_content.splitlines() if line.startswith("Dialogue:"))
        assert dialogue_line.endswith("IT'S 50:50 HUGE")

    def test_filter_chain_ends_with_setsar_and_format(self, wrapper: ShortsFFmpeg, tmp_path) -> None:
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "90 PERCENT", 1.0)
        cmd = mock_run.call_args[0][0]
        vf = cmd[cmd.index("-vf") + 1]
        assert vf.endswith(",setsar=1,format=yuv420p")


class TestConcatSegmentsVideoOnly:
    def test_warns_but_does_not_raise_when_a_segment_sar_is_not_1_1(
        self, wrapper: ShortsFFmpeg, caplog
    ) -> None:
        # Tripwire for any future segment-producing path added without going
        # through finalize_filter — this must never abort the run, only log.
        sar_values = iter(["1:1", "17485:17484", "1:1"])

        def fake_run(cmd, **kwargs):
            if cmd[0] == wrapper._ffprobe:
                return MagicMock(returncode=0, stdout=next(sar_values), stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            with caplog.at_level("WARNING"):
                wrapper.concat_segments_video_only(["/a.mp4", "/b.mp4", "/c.mp4"], "/out.mp4")

        assert any("17485:17484" in r.message or "/b.mp4" in r.message for r in caplog.records)

    def test_does_not_warn_when_all_segments_are_1_1(self, wrapper: ShortsFFmpeg, caplog) -> None:
        def fake_run(cmd, **kwargs):
            if cmd[0] == wrapper._ffprobe:
                return MagicMock(returncode=0, stdout="1:1", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            with caplog.at_level("WARNING"):
                wrapper.concat_segments_video_only(["/a.mp4", "/b.mp4"], "/out.mp4")

        assert not any("setsar" in r.message.lower() or "sar" in r.message.lower() for r in caplog.records)

    def test_still_concatenates_even_when_sar_mismatch_detected(self, wrapper: ShortsFFmpeg) -> None:
        # The pre-concat ffprobe check is advisory only — it must never block
        # or alter the actual concat call.
        def fake_run(cmd, **kwargs):
            if cmd[0] == wrapper._ffprobe:
                return MagicMock(returncode=0, stdout="17485:17484", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            wrapper.concat_segments_video_only(["/a.mp4", "/b.mp4"], "/out.mp4")

        concat_calls = [c for c in mock_run.call_args_list if "-filter_complex" in c.args[0]]
        assert len(concat_calls) == 1
        assert concat_calls[0].args[0][-1] == "/out.mp4"


class TestVerticalConvertCustomDimensions:
    def test_16_9_target_dimensions_appear_in_filter_chain(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.vertical_convert(
                "/in.mp4", "/out.mp4", "center_crop", out_width=1920, out_height=1080,
            )
        args = mock_run.call_args[0][0]
        filter_complex = args[args.index("-filter_complex") + 1]
        assert "scale=1920:1080" in filter_complex
        assert "crop=1920:1080" in filter_complex

    def test_1_1_target_dimensions_appear_in_filter_chain(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.vertical_convert(
                "/in.mp4", "/out.mp4", "blur_pad", out_width=1080, out_height=1080,
            )
        args = mock_run.call_args[0][0]
        filter_complex = args[args.index("-filter_complex") + 1]
        assert "scale=1080:1080" in filter_complex
        assert "crop=1080:1080" in filter_complex

    def test_default_dimensions_unchanged_when_omitted(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.vertical_convert("/in.mp4", "/out.mp4", "center_crop")
        args = mock_run.call_args[0][0]
        filter_complex = args[args.index("-filter_complex") + 1]
        assert "scale=1080:1920" in filter_complex


class TestApplyKenBurnsCustomDimensions:
    def test_16_9_target_appears_in_zoompan_and_upscale(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns(
                "/in.mp4", "/out.mp4", 3.0, "in", False, out_width=1920, out_height=1080,
            )
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "s=1920x1080" in vf
        assert "scale=7680:-2" in vf  # 1920 * 4

    def test_default_dimensions_unchanged_when_omitted(self, wrapper: ShortsFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns("/in.mp4", "/out.mp4", 3.0, "in", False)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "s=1080x1920" in vf


class TestGeneratePunchCardCustomDimensions:
    def test_1_1_target_appears_in_playres_and_lavfi_source(
        self, wrapper: ShortsFFmpeg, tmp_path
    ) -> None:
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(
                output_path, "90 PERCENT", 1.0, out_width=1080, out_height=1080,
            )
        cmd = mock_run.call_args[0][0]
        source = cmd[cmd.index("-i") + 1]
        assert "s=1080x1080" in source
        ass_content = (tmp_path / "card.mp4.card.ass").read_text(encoding="utf-8")
        assert "PlayResX: 1080" in ass_content
        assert "PlayResY: 1080" in ass_content

    def test_default_dimensions_unchanged_when_omitted(
        self, wrapper: ShortsFFmpeg, tmp_path
    ) -> None:
        output_path = str(tmp_path / "card.mp4")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.generate_punch_card(output_path, "90 PERCENT", 1.0)
        cmd = mock_run.call_args[0][0]
        source = cmd[cmd.index("-i") + 1]
        assert "s=1080x1920" in source
