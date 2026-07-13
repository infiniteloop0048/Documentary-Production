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
