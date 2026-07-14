"""Unit tests for ClipStoryFFmpeg — subprocess mocked, no real ffmpeg execution."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docu_studio.clipstory.clipstory_ffmpeg import ClipStoryFFmpeg
from docu_studio.clipstory.clipstory_pacing import ReconciliationPlan
from docu_studio.media.ffmpeg_wrapper import FFmpegError


@pytest.fixture
def wrapper() -> ClipStoryFFmpeg:
    with patch("docu_studio.media.ffmpeg_wrapper.imageio_ffmpeg") as mock_ffmpeg_mod:
        mock_ffmpeg_mod.get_ffmpeg_exe.return_value = "/fake/ffmpeg"
        with patch("docu_studio.media.ffmpeg_wrapper.platform_layer") as mock_pl:
            mock_pl.ffprobe_exe.return_value = "/fake/ffprobe"
            return ClipStoryFFmpeg()


class TestNormalizeClip:
    def test_16_9_uses_1920x1080_scale_pad(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.normalize_clip("/in.mp4", "16:9", "/out.mp4")
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert "scale=1920:1080" in vf
        assert "pad=1920:1080" in vf
        assert "setsar=1,format=yuv420p" in vf

    def test_9_16_uses_1080x1920_scale_pad(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.normalize_clip("/in.mp4", "9:16", "/out.mp4")
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert "scale=1080:1920" in vf
        assert "pad=1080:1920" in vf

    def test_unknown_resolution_raises(self, wrapper: ClipStoryFFmpeg) -> None:
        with pytest.raises(ValueError, match="output_resolution"):
            wrapper.normalize_clip("/in.mp4", "4:3", "/out.mp4")

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.normalize_clip("/in.mp4", "16:9", "/out.mp4")


class TestApplyAtempo:
    def test_atempo_filter_includes_speed_factor(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_atempo("/in.mp3", 1.1, "/out.mp3")
        args = mock_run.call_args[0][0]
        af = args[args.index("-filter:a") + 1]
        assert af == "atempo=1.1"


class TestApplyReconciliation:
    def test_pad_action_uses_apad_filter(self, wrapper: ClipStoryFFmpeg) -> None:
        plan = ReconciliationPlan(action="pad", adjustment_seconds=2.0)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_reconciliation("/in.mp3", plan, target_duration=10.0, output_path="/out.mp3")
        args = mock_run.call_args[0][0]
        af = args[args.index("-af") + 1]
        assert "apad=pad_dur=2.0" in af

    def test_trim_fade_action_uses_atrim_and_afade(self, wrapper: ClipStoryFFmpeg) -> None:
        plan = ReconciliationPlan(action="trim_fade", adjustment_seconds=0.5)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_reconciliation("/in.mp3", plan, target_duration=10.0, output_path="/out.mp3")
        args = mock_run.call_args[0][0]
        af = args[args.index("-af") + 1]
        assert "atrim=0:10.0" in af
        assert "afade=t=out" in af

    def test_none_action_copies_file(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        src = tmp_path / "in.mp3"
        src.write_bytes(b"fake audio data")
        dst = tmp_path / "out.mp3"
        plan = ReconciliationPlan(action="none", adjustment_seconds=0.0)
        wrapper.apply_reconciliation(str(src), plan, target_duration=10.0, output_path=str(dst))
        assert dst.read_bytes() == b"fake audio data"


class TestExtractPosterFrame:
    def test_extracts_single_frame_at_timestamp(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.extract_poster_frame("/in.mp4", 1.5, "/out.jpg")
        args = mock_run.call_args[0][0]
        assert "-ss" in args
        assert args[args.index("-ss") + 1] == "1.5"
        assert "-frames:v" in args


class TestBurnCaptions(object):
    def test_filter_string_uses_subtitles_and_finalizes(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("dummy")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions("/in.mp4", str(ass_path), "/out.mp4")
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert vf.startswith("subtitles=captions.ass")
        assert "setsar=1,format=yuv420p" in vf

    def test_runs_with_cwd_set_to_ass_directory(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("dummy")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions("/in.mp4", str(ass_path), "/out.mp4")
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("dummy")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.burn_captions("/in.mp4", str(ass_path), "/out.mp4")


class TestMixMusicBed:
    def test_uses_ducking_filtergraph_and_loops_music_input(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mix_music_bed("/voice.mp4", "/music.mp3", 30.0, "/out.m4a")
        args = mock_run.call_args[0][0]
        assert "-stream_loop" in args
        assert args[args.index("-stream_loop") + 1] == "-1"
        assert "-map" in args and args[args.index("-map") + 1] == "[aout]"
        fc = args[args.index("-filter_complex") + 1]
        assert "sidechaincompress" in fc and "amix" in fc

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.mix_music_bed("/voice.mp4", "/music.mp3", 30.0, "/out.m4a")


class TestConcatSegmentsWithXfade:
    def test_two_segments_chains_xfade_and_acrossfade(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_with_xfade(
                ["/a.mp4", "/b.mp4"], [10.0, 8.0], 0.5, "/out.mp4",
            )
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        assert "xfade=transition=fade:duration=0.50:offset=9.500" in fc
        assert "acrossfade=d=0.50" in fc
        assert "setsar=1,format=yuv420p" in fc
        assert args[args.index("-map") + 1] == "[vout]"
        assert args[args.index("-map", args.index("-map") + 1) + 1] == "[aout]"

    def test_three_segments_chains_cumulative_offsets(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_with_xfade(
                ["/a.mp4", "/b.mp4", "/c.mp4"], [10.0, 8.0, 6.0], 0.5, "/out.mp4",
            )
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        # offset 1: 10.0 - 0.5 = 9.5; offset 2: (9.5+8.0) - 0.5 = 17.0
        assert "offset=9.500" in fc
        assert "offset=17.000" in fc
        assert fc.count("xfade=") == 2
        assert fc.count("acrossfade=") == 2

    def test_fewer_than_two_segments_raises(self, wrapper: ClipStoryFFmpeg) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            wrapper.concat_segments_with_xfade(["/a.mp4"], [10.0], 0.5, "/out.mp4")

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.concat_segments_with_xfade(
                    ["/a.mp4", "/b.mp4"], [10.0, 8.0], 0.5, "/out.mp4",
                )

    def test_fps_normalized_before_xfade_for_every_segment(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_with_xfade(
                ["/a.mp4", "/b.mp4", "/c.mp4"], [10.0, 8.0, 6.0], 0.5, "/out.mp4",
            )
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        assert "[0:v]fps=30[v0]" in fc
        assert "[1:v]fps=30[v1]" in fc
        assert "[2:v]fps=30[v2]" in fc


class TestApplyReconciliationNoneBranchErrorHandling:
    def test_copy_failure_raises_ffmpeg_error_not_os_error(self, wrapper: ClipStoryFFmpeg) -> None:
        from docu_studio.clipstory.clipstory_pacing import ReconciliationPlan
        plan = ReconciliationPlan(action="none", adjustment_seconds=0.0)
        with patch("shutil.copy", side_effect=OSError("disk full")):
            with pytest.raises(FFmpegError, match="disk full"):
                wrapper.apply_reconciliation("/in.mp3", plan, 10.0, "/out.mp3")


class TestConcatSegmentsNoRedundantScale:
    def test_filter_complex_has_no_scale_only_fps(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments(["/a.mp4", "/b.mp4"], "16:9", "/out.mp4")
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        assert "scale=" not in fc
        assert "fps=30" in fc


class TestConcatSegments:
    def test_uses_fps_and_concat(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments(["/a.mp4", "/b.mp4"], "16:9", "/out.mp4")
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        assert "fps=30" in fc
        assert "concat=n=2:v=1:a=1" in fc

    def test_9_16_resolution(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments(["/a.mp4", "/b.mp4"], "9:16", "/out.mp4")
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        assert "fps=30" in fc

    def test_unknown_resolution_raises(self, wrapper: ClipStoryFFmpeg) -> None:
        with pytest.raises(ValueError, match="output_resolution"):
            wrapper.concat_segments(["/a.mp4"], "4:3", "/out.mp4")
