"""Unit tests for PipelineRunner."""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.pipeline.events import ErrorEvent, ProgressEvent
from docu_studio.pipeline.runner import PipelineRunner, RunMode, RunStatus
from docu_studio.pipeline.stages.scene_break import Scene


def _make_runner(tmp_path: Path, *, mode: RunMode = RunMode.GUIDED, topic: str = "Test") -> PipelineRunner:
    return PipelineRunner(
        topic=topic,
        duration_minutes=5,
        mode=mode,
        llm=MagicMock(),
        tts=MagicMock(),
        footage_providers=[MagicMock()],
        output_base=tmp_path,
    )


def _drain(q: queue.Queue, timeout: float = 5.0) -> list:
    """Drain queue until None sentinel is found."""
    items = []
    while True:
        try:
            item = q.get(timeout=timeout)
            if item is None:
                break
            items.append(item)
        except queue.Empty:
            break
    return items


def _run_with_mocked_stages(runner: PipelineRunner, tmp_path: Path) -> list:
    """Execute runner with all pipeline stages mocked."""
    mock_scene = Scene(index=1, title="S", narration="N")
    mock_scene.audio_path = str(tmp_path / "audio" / "scene_001.mp3")
    mock_scene.audio_duration = 10.0
    mock_scene.video_path = str(tmp_path / "video" / "scene_001.mp4")
    mock_scene.video_duration = 10.0

    with patch("docu_studio.pipeline.runner.create_project_folder", return_value=tmp_path), \
         patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
         patch("docu_studio.pipeline.runner.script_gen.run", return_value="script text"), \
         patch("docu_studio.pipeline.runner.scene_break.run", return_value=[mock_scene]), \
         patch("docu_studio.pipeline.runner.tts_gen.run"), \
         patch("docu_studio.pipeline.runner.keyword_extract.run"), \
         patch("docu_studio.pipeline.runner.footage_assembly.run"), \
         patch("docu_studio.pipeline.runner.fcpxml_export.run"), \
         patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
        runner.start()
        runner.join(timeout=10.0)

    return _drain(runner.event_queue)


class TestPipelineRunnerInit:
    def test_creates_event_queue(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        assert isinstance(runner.event_queue, queue.Queue)

    def test_creates_cancel_event(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        assert isinstance(runner.cancel_event, threading.Event)

    def test_is_daemon_thread(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        assert runner.daemon is True


class TestPipelineRunnerGuidedMode:
    def test_emits_sentinel_after_run(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        _run_with_mocked_stages(runner, tmp_path)
        # sentinel (None) was consumed by _drain; runner should be done
        assert not runner.is_alive()

    def test_emits_completion_progress_event(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        events = _run_with_mocked_stages(runner, tmp_path)
        progress = [e for e in events if isinstance(e, ProgressEvent)]
        assert any("completed" in e.message.lower() or e.stage == "Done" for e in progress)


class TestPipelineRunnerCompletionDurationMismatch:
    def test_done_message_includes_mismatch_when_script_falls_short(self, tmp_path: Path) -> None:
        # duration_minutes=5 -> target 750 words @ 150 wpm; script only has 50.
        runner = _make_runner(tmp_path)
        mock_scene = Scene(index=1, title="S", narration="N")
        mock_scene.audio_path = str(tmp_path / "audio" / "scene_001.mp3")
        mock_scene.audio_duration = 10.0
        mock_scene.video_path = str(tmp_path / "video" / "scene_001.mp4")
        mock_scene.video_duration = 10.0

        with patch("docu_studio.pipeline.runner.create_project_folder", return_value=tmp_path), \
             patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
             patch("docu_studio.pipeline.runner.script_gen.run", return_value="word " * 50), \
             patch("docu_studio.pipeline.runner.scene_break.run", return_value=[mock_scene]), \
             patch("docu_studio.pipeline.runner.tts_gen.run"), \
             patch("docu_studio.pipeline.runner.keyword_extract.run"), \
             patch("docu_studio.pipeline.runner.footage_assembly.run"), \
             patch("docu_studio.pipeline.runner.fcpxml_export.run"), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        events = _drain(runner.event_queue)
        done_events = [e for e in events if isinstance(e, ProgressEvent) and e.stage == "Done"]
        assert done_events, "expected a Done ProgressEvent"
        message = done_events[0].message.lower()
        assert "requested" in message
        assert "5 min" in message

    def test_done_message_has_no_mismatch_when_script_meets_target(self, tmp_path: Path) -> None:
        # duration_minutes=5 -> target 750 words @ 150 wpm; script matches exactly.
        runner = _make_runner(tmp_path)
        mock_scene = Scene(index=1, title="S", narration="N")
        mock_scene.audio_path = str(tmp_path / "audio" / "scene_001.mp3")
        mock_scene.audio_duration = 10.0
        mock_scene.video_path = str(tmp_path / "video" / "scene_001.mp4")
        mock_scene.video_duration = 10.0

        with patch("docu_studio.pipeline.runner.create_project_folder", return_value=tmp_path), \
             patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
             patch("docu_studio.pipeline.runner.script_gen.run", return_value="word " * 750), \
             patch("docu_studio.pipeline.runner.scene_break.run", return_value=[mock_scene]), \
             patch("docu_studio.pipeline.runner.tts_gen.run"), \
             patch("docu_studio.pipeline.runner.keyword_extract.run"), \
             patch("docu_studio.pipeline.runner.footage_assembly.run"), \
             patch("docu_studio.pipeline.runner.fcpxml_export.run"), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        events = _drain(runner.event_queue)
        done_events = [e for e in events if isinstance(e, ProgressEvent) and e.stage == "Done"]
        assert done_events, "expected a Done ProgressEvent"
        assert done_events[0].message == "Pipeline completed successfully."


class TestPipelineRunnerCancellation:
    def test_cancel_before_start_results_in_cancelled(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        runner.cancel_event.set()

        with patch("docu_studio.pipeline.runner.create_project_folder", return_value=tmp_path), \
             patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
             patch("docu_studio.pipeline.runner.script_gen.run", return_value="script"), \
             patch("docu_studio.pipeline.runner.scene_break.run", return_value=[]), \
             patch("docu_studio.pipeline.runner.tts_gen.run"), \
             patch("docu_studio.pipeline.runner.keyword_extract.run"), \
             patch("docu_studio.pipeline.runner.footage_assembly.run"), \
             patch("docu_studio.pipeline.runner.fcpxml_export.run"), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        assert runner._status == RunStatus.CANCELLED


class TestPipelineRunnerFullAutoMode:
    def test_full_auto_calls_topic_discovery(self, tmp_path: Path) -> None:
        from docu_studio.pipeline.stages.topic_discovery import TopicResult
        runner = _make_runner(tmp_path, mode=RunMode.FULL_AUTO)
        mock_scene = Scene(index=1, title="S", narration="N")
        mock_scene.audio_path = str(tmp_path / "audio" / "scene_001.mp3")
        mock_scene.audio_duration = 10.0
        mock_scene.video_path = str(tmp_path / "video" / "scene_001.mp4")
        mock_scene.video_duration = 10.0

        with patch("docu_studio.pipeline.runner.create_project_folder", return_value=tmp_path), \
             patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
             patch("docu_studio.pipeline.stages.topic_discovery.run",
                   return_value=TopicResult(topic="AI Topic", source="ai_suggested")) as mock_td, \
             patch("docu_studio.pipeline.runner.script_gen.run", return_value="script"), \
             patch("docu_studio.pipeline.runner.scene_break.run", return_value=[mock_scene]), \
             patch("docu_studio.pipeline.runner.tts_gen.run"), \
             patch("docu_studio.pipeline.runner.keyword_extract.run"), \
             patch("docu_studio.pipeline.runner.footage_assembly.run"), \
             patch("docu_studio.pipeline.runner.fcpxml_export.run"), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        mock_td.assert_called_once()
        assert runner.topic == "AI Topic"


class TestPipelineRunnerErrorHandling:
    def test_exception_in_stage_emits_fatal_error_event(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)

        with patch("docu_studio.pipeline.runner.create_project_folder",
                   side_effect=RuntimeError("disk full")), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        events = _drain(runner.event_queue)
        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert error_events
        assert error_events[0].fatal is True

    def test_runner_status_is_failed_on_exception(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)

        with patch("docu_studio.pipeline.runner.create_project_folder",
                   side_effect=RuntimeError("boom")), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        assert runner._status == RunStatus.FAILED
