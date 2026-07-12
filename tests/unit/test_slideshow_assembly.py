"""Unit tests for slideshow_assembly — ffmpeg mocked, no real ffmpeg or I/O."""
from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from docu_studio.slideshow.slideshow_assembly import assemble_slideshow, split_duration_evenly


class TestSplitDurationEvenly:
    def test_even_split_sums_exactly(self) -> None:
        durations = split_duration_evenly(10.0, 4)
        assert len(durations) == 4
        assert sum(durations) == pytest.approx(10.0)

    def test_remainder_absorbed_by_last_segment(self) -> None:
        durations = split_duration_evenly(10.0, 3)
        assert durations[0] == durations[1]
        assert sum(durations) == pytest.approx(10.0)

    def test_single_image_gets_full_duration(self) -> None:
        assert split_duration_evenly(7.5, 1) == [7.5]

    def test_zero_count_raises(self) -> None:
        with pytest.raises(ValueError, match="count must be positive"):
            split_duration_evenly(10.0, 0)


class TestAssembleSlideshow:
    def test_builds_one_segment_per_image_in_order(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        images = ["/img0.jpg", "/img1.jpg", "/img2.jpg"]
        assemble_slideshow(
            image_paths=images,
            audio_path="/narration.mp3",
            audio_duration=9.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        assert ffmpeg.apply_ken_burns_image.call_count == 3
        first_call_args = ffmpeg.apply_ken_burns_image.call_args_list[0].args
        assert first_call_args[0] == "/img0.jpg"
        assert first_call_args[3] == "in"   # direction_for_index(0)
        assert first_call_args[4:] == (1080, 1920)

    def test_concats_then_muxes(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"],
            audio_path="/narration.mp3",
            audio_duration=3.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        ffmpeg.concat_segments_video_only.assert_called_once()
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )

    def test_segment_failure_raises_with_index_and_image(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        ffmpeg.apply_ken_burns_image.side_effect = RuntimeError("ffmpeg exploded")
        event_queue: "queue.Queue[object]" = queue.Queue()
        with pytest.raises(RuntimeError, match="Segment 0.*img0.jpg"):
            assemble_slideshow(
                image_paths=["/img0.jpg"],
                audio_path="/narration.mp3",
                audio_duration=3.0,
                ffmpeg=ffmpeg,
                scene_dir=tmp_path,
                output_path=tmp_path / "final.mp4",
                out_width=1080,
                out_height=1920,
                event_queue=event_queue,
            )

    def test_progress_events_emitted(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"],
            audio_path="/narration.mp3",
            audio_duration=3.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        stages = []
        while not event_queue.empty():
            ev = event_queue.get_nowait()
            if hasattr(ev, "stage"):
                stages.append(ev.stage)
        assert "Slideshow Assembly" in stages
        assert "Slideshow Mux" in stages


class TestCrossfadeSegmentDurations:
    def test_inflates_all_but_last_segment(self) -> None:
        from docu_studio.slideshow.slideshow_assembly import crossfade_segment_durations
        result = crossfade_segment_durations([3.0, 3.0, 3.0], 0.5)
        assert result == pytest.approx([3.5, 3.5, 3.0])

    def test_single_segment_unchanged(self) -> None:
        from docu_studio.slideshow.slideshow_assembly import crossfade_segment_durations
        assert crossfade_segment_durations([9.0], 0.5) == [9.0]


class TestAssembleSlideshowCrossfade:
    def test_crossfade_uses_xfade_concat_with_inflated_durations(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg", "/img1.jpg", "/img2.jpg"],
            audio_path="/narration.mp3",
            audio_duration=9.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
            transition="crossfade",
        )
        ffmpeg.concat_segments_video_only.assert_not_called()
        ffmpeg.concat_segments_with_xfade.assert_called_once()
        call_args = ffmpeg.concat_segments_with_xfade.call_args.args
        assert call_args[1] == pytest.approx([3.5, 3.5, 3.0])  # durations, inflated
        assert call_args[2] == 0.5  # transition_duration

    def test_crossfade_segments_rendered_with_inflated_durations(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg", "/img1.jpg", "/img2.jpg"],
            audio_path="/narration.mp3",
            audio_duration=9.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
            transition="crossfade",
        )
        first_seg_duration = ffmpeg.apply_ken_burns_image.call_args_list[0].args[2]
        last_seg_duration = ffmpeg.apply_ken_burns_image.call_args_list[2].args[2]
        assert first_seg_duration == pytest.approx(3.5)
        assert last_seg_duration == pytest.approx(3.0)

    def test_single_image_crossfade_falls_back_to_hard_cut(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"],
            audio_path="/narration.mp3",
            audio_duration=3.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
            transition="crossfade",
        )
        ffmpeg.concat_segments_with_xfade.assert_not_called()
        ffmpeg.concat_segments_video_only.assert_called_once()

    def test_hard_cut_default_still_uses_concat_segments_video_only(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg", "/img1.jpg"],
            audio_path="/narration.mp3",
            audio_duration=6.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        ffmpeg.concat_segments_with_xfade.assert_not_called()
        ffmpeg.concat_segments_video_only.assert_called_once()


class TestAssembleSlideshowOverlays:
    def test_overlays_applied_when_vignette_enabled(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue, vignette=True,
        )
        ffmpeg.apply_overlays.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"), str(tmp_path / "slideshow_overlay.mp4"), True, False,
        )
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_overlay.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )

    def test_overlays_skipped_when_both_flags_false(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
        )
        ffmpeg.apply_overlays.assert_not_called()


class TestAssembleSlideshowCaptions:
    def test_captions_burned_when_enabled(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
            captions=True, script_text="hello there world",
        )
        ffmpeg.burn_captions.assert_called_once()
        call_args = ffmpeg.burn_captions.call_args.args
        assert call_args[0] == str(tmp_path / "slideshow_concat.mp4")
        assert call_args[1] == str(tmp_path / "captions.ass")
        assert (tmp_path / "captions.ass").exists()
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_captioned.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )

    def test_captions_skipped_when_disabled(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
        )
        ffmpeg.burn_captions.assert_not_called()

    def test_captions_run_after_overlays_on_overlay_output(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
            vignette=True, captions=True, script_text="hi",
        )
        assert ffmpeg.burn_captions.call_args.args[0] == str(tmp_path / "slideshow_overlay.mp4")


class TestAssembleSlideshowMusic:
    def test_music_mixed_into_narration_before_mux(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
            music_path="/music/track.mp3",
        )
        ffmpeg.mix_music_bed.assert_called_once_with(
            "/narration.mp3", "/music/track.mp3", 3.0, str(tmp_path / "narration_with_music.mp3"),
        )
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"),
            str(tmp_path / "narration_with_music.mp3"),
            str(tmp_path / "final.mp4"),
        )

    def test_no_music_path_skips_mixing(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
        )
        ffmpeg.mix_music_bed.assert_not_called()
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )
