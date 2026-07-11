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
