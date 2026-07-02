"""Integration tests: pipeline_log.txt is written to project folder and sanitized."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.pipeline.events import LogEvent, LogLevel
from docu_studio.pipeline.runner import PipelineRunner, RunMode, RunStatus
from docu_studio.pipeline.stages.scene_break import Scene

_FAKE_KEY = "sk-ant-INTEGTEST-FAKE-KEY-XYZ"


def _make_runner(tmp_path: Path, *, sensitive_keys: list[str] | None = None) -> PipelineRunner:
    return PipelineRunner(
        topic="Pipeline Log Test",
        duration_minutes=5,
        mode=RunMode.GUIDED,
        llm=MagicMock(),
        tts=MagicMock(),
        footage_providers=[MagicMock()],
        output_base=tmp_path,
        sensitive_keys=sensitive_keys or [],
    )


def _make_scene(tmp_path: Path) -> Scene:
    s = Scene(index=1, title="S1", narration="N1")
    s.audio_path = str(tmp_path / "audio" / "scene_001.mp3")
    s.audio_duration = 10.0
    s.video_path = str(tmp_path / "video" / "scene_001.mp4")
    s.video_duration = 10.0
    return s


def _find_project_dir(tmp_path: Path) -> Path:
    dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert dirs, "no project folder found in tmp_path"
    return dirs[0]


def _run_success(runner: PipelineRunner, tmp_path: Path, *, script_gen_side_effect=None) -> None:
    mock_scene = _make_scene(tmp_path)
    script_gen_fn = script_gen_side_effect or (lambda *a, **k: "script text")
    with patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
         patch("docu_studio.pipeline.runner.script_gen.run", side_effect=script_gen_fn), \
         patch("docu_studio.pipeline.runner.scene_break.run", return_value=[mock_scene]), \
         patch("docu_studio.pipeline.runner.tts_gen.run"), \
         patch("docu_studio.pipeline.runner.keyword_extract.run"), \
         patch("docu_studio.pipeline.runner.footage_assembly.run"), \
         patch("docu_studio.pipeline.runner.fcpxml_export.run"), \
         patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
        runner.start()
        runner.join(timeout=10.0)


class TestPipelineLogCreated:
    def test_log_file_exists_after_successful_run(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        _run_success(runner, tmp_path)
        log = _find_project_dir(tmp_path) / "pipeline_log.txt"
        assert log.exists(), "pipeline_log.txt was not created in the project folder"

    def test_log_file_has_content(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        _run_success(runner, tmp_path)
        content = (_find_project_dir(tmp_path) / "pipeline_log.txt").read_text(encoding="utf-8")
        assert len(content) > 0

    def test_log_contains_progress_lines(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        _run_success(runner, tmp_path)
        content = (_find_project_dir(tmp_path) / "pipeline_log.txt").read_text(encoding="utf-8")
        assert "[PROGRESS]" in content or "[INFO]" in content


class TestPipelineLogSanitization:
    def test_raw_api_key_not_written_to_log(self, tmp_path: Path) -> None:
        """A LogEvent whose message contains the raw key must be redacted on disk."""
        runner = _make_runner(tmp_path, sensitive_keys=[_FAKE_KEY])

        def script_gen_leaks_key(topic, duration, llm, folder, event_queue):
            event_queue.put(LogEvent(
                message=f"Debug: using API key {_FAKE_KEY} for generation",
                level=LogLevel.INFO,
            ))
            return "script text"

        _run_success(runner, tmp_path, script_gen_side_effect=script_gen_leaks_key)

        content = (_find_project_dir(tmp_path) / "pipeline_log.txt").read_text(encoding="utf-8")
        assert _FAKE_KEY not in content, "Raw API key found in pipeline_log.txt"
        assert "***REDACTED***" in content, "Redaction marker missing from pipeline_log.txt"


class TestPipelineLogOnFailure:
    def test_log_file_exists_after_stage_failure(self, tmp_path: Path) -> None:
        """Log file must be written even when a stage raises an exception."""
        runner = _make_runner(tmp_path)

        def script_gen_fails(*args, **kwargs):
            raise RuntimeError("LLM service unavailable")

        with patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
             patch("docu_studio.pipeline.runner.script_gen.run", side_effect=script_gen_fails), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        assert runner._status == RunStatus.FAILED
        log = _find_project_dir(tmp_path) / "pipeline_log.txt"
        assert log.exists(), "pipeline_log.txt must exist even after a failed run"

    def test_log_records_error_on_failure(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)

        def script_gen_fails(*args, **kwargs):
            raise RuntimeError("LLM service unavailable")

        with patch("docu_studio.pipeline.runner.FFmpegWrapper"), \
             patch("docu_studio.pipeline.runner.script_gen.run", side_effect=script_gen_fails), \
             patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            runner.start()
            runner.join(timeout=10.0)

        content = (_find_project_dir(tmp_path) / "pipeline_log.txt").read_text(encoding="utf-8")
        assert "[ERROR]" in content
        assert "LLM service unavailable" in content
