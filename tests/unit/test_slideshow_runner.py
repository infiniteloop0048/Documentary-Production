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


class TestPhase3Wiring:
    def test_defaults_produce_config_matching_phase1_phase2(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(image)], tts=MagicMock(), output_base=tmp_path,
        )
        assert runner.config.transition == "cut"
        assert runner.config.vignette is False
        assert runner.config.music_enabled is False

    def test_phase3_kwargs_reach_config(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(image)], tts=MagicMock(), output_base=tmp_path,
            transition="crossfade", vignette=True, grain=True, captions=True,
            music_enabled=True, music_provider="local_folder", music_folder="/tunes",
            jamendo_client_id="fake-id",
        )
        assert runner.config.transition == "crossfade"
        assert runner.config.vignette is True
        assert runner.config.grain is True
        assert runner.config.captions is True
        assert runner.config.music_enabled is True
        assert runner.config.music_provider == "local_folder"
        assert runner.config.music_folder == "/tunes"
        assert runner.config.jamendo_client_id == "fake-id"

    def test_music_enabled_resolves_track_before_assembly(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0
        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
            music_enabled=True, music_provider="local_folder", music_folder="/tunes",
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.resolve_music_track") as mock_resolve, \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            mock_resolve.return_value = ("/tunes/song.mp3", "song.mp3")
            runner.run()
        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.kwargs["provider_name"] == "local_folder"
        assert mock_resolve.call_args.kwargs["local_folder"] == "/tunes"
        assert mock_assemble.call_args.kwargs["music_path"] == "/tunes/song.mp3"

    def test_music_enabled_but_unresolved_still_completes(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0
        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
            music_enabled=True, music_provider="local_folder", music_folder="/empty",
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.resolve_music_track", return_value=None), \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            runner.run()
        assert runner._status == SlideshowRunStatus.COMPLETED
        assert mock_assemble.call_args.kwargs["music_path"] is None

    def test_captions_pass_script_text_into_assembly(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0
        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
            captions=True,
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            runner.run()
        assert mock_assemble.call_args.kwargs["captions"] is True
        assert mock_assemble.call_args.kwargs["script_text"] == "Hello world."
