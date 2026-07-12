"""Unit tests for SlideshowFFmpeg — subprocess mocked, no real ffmpeg
required, matching test_shorts_ffmpeg.py's convention."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg


@pytest.fixture
def wrapper() -> SlideshowFFmpeg:
    with patch("docu_studio.media.ffmpeg_wrapper.imageio_ffmpeg") as mock_ffmpeg_mod:
        mock_ffmpeg_mod.get_ffmpeg_exe.return_value = "/fake/ffmpeg"
        with patch("docu_studio.media.ffmpeg_wrapper.platform_layer") as mock_pl:
            mock_pl.ffprobe_exe.return_value = "/fake/ffprobe"
            return SlideshowFFmpeg()


class TestFinalizeFilter:
    def test_appends_sar_pixfmt_suffix(self, wrapper: SlideshowFFmpeg) -> None:
        assert wrapper._finalize_filter("scale=100:100") == "scale=100:100,setsar=1,format=yuv420p"


class TestApplyKenBurnsImage:
    def test_loops_the_still_image_input(self, wrapper: SlideshowFFmpeg) -> None:
        # A still image is a single-frame source; without -loop 1 ffmpeg
        # would exhaust it after one frame and zoompan would have nothing
        # to animate across `duration` seconds.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)
        cmd = mock_run.call_args[0][0]
        assert "-loop" in cmd
        assert cmd[cmd.index("-loop") + 1] == "1"
        assert cmd[cmd.index("-i") - 1] == "1"  # -loop 1 immediately precedes -i

    def test_crops_to_target_aspect_before_upscale(self, wrapper: SlideshowFFmpeg) -> None:
        # Unlike Shorts (which pre-crops to 1080x1920 via a separate
        # vertical_convert pass before Ken Burns ever runs), a still image
        # arrives at its native size — the crop-to-target-aspect step has
        # to be folded into this same filter chain.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1920, 1080)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "scale=1920:1080:force_original_aspect_ratio=increase" in vf
        assert "crop=1920:1080" in vf

    def test_upscales_4x_before_zoompan(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "scale=4320:-2:flags=lanczos" in vf

    def test_zoom_in_expression_is_non_accumulating(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", duration=1.0, direction="in",
                                           out_width=1080, out_height=1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        # duration=1.0 @ fps=30 -> frames=30, denom=29
        assert "z='1+0.08*on/29'" in vf

    def test_zoom_out_expression(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", duration=1.0, direction="out",
                                           out_width=1080, out_height=1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert "z='1.08-0.08*on/29'" in vf

    def test_finalize_suffix_present(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf.endswith("setsar=1,format=yuv420p")

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError, match="boom"):
                wrapper.apply_ken_burns_image("/photo.jpg", "/out.mp4", 3.0, "in", 1080, 1920)


class TestConcatSegmentsVideoOnly:
    def test_builds_filter_complex_concat(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_video_only(["/a.mp4", "/b.mp4", "/c.mp4"], "/out.mp4")
        cmd = mock_run.call_args[0][0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert filter_complex == "[0:v][1:v][2:v]concat=n=3:v=1:a=0[vout]"
        assert cmd.count("-i") == 3


class TestXfadeOffsets:
    def test_two_segments(self) -> None:
        # seg0=3.5s, seg1=3.0s, transition=0.5s -> offset = 3.5 - 0.5 = 3.0
        offsets = SlideshowFFmpeg._xfade_offsets([3.5, 3.0], 0.5)
        assert offsets == pytest.approx([3.0])

    def test_three_segments_offsets_are_cumulative(self) -> None:
        # base [3,3,3] inflated to [3.5, 3.5, 3] by concat_segments_with_xfade's
        # caller (slideshow_assembly.crossfade_segment_durations) before this
        # method ever sees them.
        offsets = SlideshowFFmpeg._xfade_offsets([3.5, 3.5, 3.0], 0.5)
        assert offsets == pytest.approx([3.0, 6.0])


class TestConcatSegmentsWithXfade:
    def test_requires_at_least_two_segments(self, wrapper: SlideshowFFmpeg) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            wrapper.concat_segments_with_xfade(["/a.mp4"], [3.0], 0.5, "/out.mp4")

    def test_builds_chained_xfade_filter_complex(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_with_xfade(
                ["/a.mp4", "/b.mp4", "/c.mp4"], [3.5, 3.5, 3.0], 0.5, "/out.mp4",
            )
        cmd = mock_run.call_args[0][0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert filter_complex == (
            "[0:v][1:v]xfade=transition=fade:duration=0.50:offset=3.000[x1];"
            "[x1][2:v]xfade=transition=fade:duration=0.50:offset=6.000,"
            "setsar=1,format=yuv420p[vout]"
        )
        assert cmd[cmd.index("-map") + 1] == "[vout]"
        assert cmd.count("-i") == 3

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="xfade boom")
            with pytest.raises(FFmpegError, match="xfade boom"):
                wrapper.concat_segments_with_xfade(
                    ["/a.mp4", "/b.mp4"], [3.5, 3.0], 0.5, "/out.mp4",
                )


class TestApplyOverlays:
    def test_raises_when_neither_flag_set(self, wrapper: SlideshowFFmpeg) -> None:
        with pytest.raises(ValueError, match="at least one"):
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=False, grain=False)

    def test_vignette_only(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=True, grain=False)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf == "vignette,setsar=1,format=yuv420p"

    def test_grain_only(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=False, grain=True)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf == "noise=alls=8:allf=t,setsar=1,format=yuv420p"

    def test_both_combined_in_order(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=True, grain=True)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf == "vignette,noise=alls=8:allf=t,setsar=1,format=yuv420p"

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="overlay boom")
            with pytest.raises(FFmpegError, match="overlay boom"):
                wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=True, grain=False)


class TestBurnCaptions:
    def test_uses_subtitles_filter_with_bare_filename(self, wrapper: SlideshowFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("[Script Info]\n", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions(str(tmp_path / "in.mp4"), str(ass_path), str(tmp_path / "out.mp4"))
        cmd = mock_run.call_args[0][0]
        vf = cmd[cmd.index("-vf") + 1]
        assert vf == "subtitles=captions.ass,setsar=1,format=yuv420p"

    def test_runs_with_cwd_set_to_ass_directory(self, wrapper: SlideshowFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("[Script Info]\n", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions(str(tmp_path / "in.mp4"), str(ass_path), str(tmp_path / "out.mp4"))
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg, tmp_path) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("[Script Info]\n", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="subtitles boom")
            with pytest.raises(FFmpegError, match="subtitles boom"):
                wrapper.burn_captions(str(tmp_path / "in.mp4"), str(ass_path), str(tmp_path / "out.mp4"))
