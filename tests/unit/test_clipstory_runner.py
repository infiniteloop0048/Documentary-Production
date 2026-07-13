"""Unit tests for ClipStoryRunner — assembly and history save mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from docu_studio.clipstory.clipstory_assembly import ClipStoryFitError
from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig
from docu_studio.clipstory.clipstory_runner import ClipStoryRunner, ClipStoryRunStatus
from docu_studio.pipeline.events import ErrorEvent, ProgressEvent


def _make_config() -> ClipStoryConfig:
    clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hello world.")]
    return ClipStoryConfig(topic="Test", clips=clips)


class TestClipStoryRunnerHappyPath:
    def test_successful_run_marks_completed_and_pushes_done_event(self, tmp_path: Path) -> None:
        with patch("docu_studio.clipstory.clipstory_runner.create_project_folder") as mock_create, \
             patch("docu_studio.clipstory.clipstory_runner.assemble_clip_story") as mock_assemble, \
             patch("docu_studio.clipstory.clipstory_runner.save_run"):
            mock_create.return_value = tmp_path
            runner = ClipStoryRunner(config=_make_config(), tts=MagicMock(), output_base=tmp_path)
            runner.run()
        assert runner._status == ClipStoryRunStatus.COMPLETED
        assert runner._final_video_path == tmp_path / "clipstory_final.mp4"
        mock_assemble.assert_called_once()
        events = []
        while True:
            ev = runner.event_queue.get_nowait()
            if ev is None:
                break
            events.append(ev)
        assert any(isinstance(e, ProgressEvent) and e.stage == "Done" for e in events)


class TestClipStoryRunnerFitHalt:
    def test_fit_error_pushes_error_event_and_marks_failed(self, tmp_path: Path) -> None:
        with patch("docu_studio.clipstory.clipstory_runner.create_project_folder") as mock_create, \
             patch("docu_studio.clipstory.clipstory_runner.assemble_clip_story") as mock_assemble, \
             patch("docu_studio.clipstory.clipstory_runner.save_run"):
            mock_create.return_value = tmp_path
            mock_assemble.side_effect = ClipStoryFitError("Clip 0: target=10.00s actual=30.00s ...")
            runner = ClipStoryRunner(config=_make_config(), tts=MagicMock(), output_base=tmp_path)
            runner.run()
        assert runner._status == ClipStoryRunStatus.FAILED
        events = []
        while True:
            ev = runner.event_queue.get_nowait()
            if ev is None:
                break
            events.append(ev)
        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1
        assert "target=10.00s" in error_events[0].message


class TestClipStoryRunnerCancellation:
    def test_cancel_before_execute_skips_assembly(self, tmp_path: Path) -> None:
        with patch("docu_studio.clipstory.clipstory_runner.create_project_folder") as mock_create, \
             patch("docu_studio.clipstory.clipstory_runner.assemble_clip_story") as mock_assemble, \
             patch("docu_studio.clipstory.clipstory_runner.save_run"):
            mock_create.return_value = tmp_path
            runner = ClipStoryRunner(config=_make_config(), tts=MagicMock(), output_base=tmp_path)
            runner.cancel_event.set()
            runner.run()
        assert runner._status == ClipStoryRunStatus.CANCELLED
        mock_assemble.assert_not_called()
