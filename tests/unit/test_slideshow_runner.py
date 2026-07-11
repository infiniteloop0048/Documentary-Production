"""Unit tests for SlideshowRunner — TTS/ffmpeg fully mocked, no real
synthesis, ffmpeg, or filesystem I/O beyond tmp_path."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.slideshow.slideshow_runner import SlideshowRunner, SlideshowRunStatus


def _drain(runner: SlideshowRunner) -> list[object]:
    events = []
    while True:
        ev = runner.event_queue.get_nowait()
        if ev is None:
            break
        events.append(ev)
    return events


class TestSlideshowRunner:
    def test_invalid_config_raises_before_thread_starts(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="image_paths"):
            SlideshowRunner(
                script_text="Hello.", image_paths=[], tts=MagicMock(), output_base=tmp_path,
            )

    def test_successful_run_sets_completed_status(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0

        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            runner.run()

        assert runner._status == SlideshowRunStatus.COMPLETED
        assert runner._final_video_path is not None
        mock_assemble.assert_called_once()
        events = _drain(runner)
        assert any(getattr(e, "stage", "") == "Done" for e in events)

    def test_cancel_before_start_short_circuits(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
        )
        runner.cancel_event.set()
        with patch("docu_studio.slideshow.slideshow_runner.save_run"):
            runner.run()
        assert runner._status == SlideshowRunStatus.CANCELLED
        tts.synthesize.assert_not_called()

    def test_missing_image_file_fails_the_run(self, tmp_path: Path) -> None:
        # SlideshowConfig only checks the list is non-empty; per-path
        # existence is validate_manual_images' job, called at execution
        # time (a file could vanish between GUI selection and Start click).
        tts = MagicMock()
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(tmp_path / "gone.jpg")],
            tts=tts, output_base=tmp_path,
        )
        with patch("docu_studio.slideshow.slideshow_runner.save_run"):
            runner.run()
        assert runner._status == SlideshowRunStatus.FAILED
        events = _drain(runner)
        assert any("not found" in getattr(e, "message", "") for e in events)
