"""PipelineRunner — background thread that orchestrates all pipeline stages."""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import IO

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.config.defaults import DEFAULT_WPM
from docu_studio.history.run_history import RunRecord, TopicSource, save_run
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline import stages
from docu_studio.pipeline.events import (
    ErrorEvent,
    LogEvent,
    LogLevel,
    ProgressEvent,
    sanitize_log_message,
)
from docu_studio.pipeline.stages import (
    fcpxml_export,
    final_merge,
    footage_assembly,
    keyword_extract,
    scene_break,
    script_gen,
    tts_gen,
)


class _TeeQueue(queue.Queue):
    """queue.Queue that mirrors every put() to an optional log file.

    The log file is opened by open_log() once the project folder exists and
    closed by close_log() in the runner's finally block.  Log writes are
    best-effort — an OSError never propagates to the caller.
    """

    def __init__(self) -> None:
        super().__init__()
        self._log_file: IO[str] | None = None
        self._sensitive_keys: list[str] = []

    def open_log(self, path: Path, sensitive_keys: list[str]) -> None:
        self._sensitive_keys = sensitive_keys
        self._log_file = path.open("w", encoding="utf-8")

    def close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            finally:
                self._log_file = None

    def put(self, item: object, block: bool = True, timeout: float | None = None) -> None:  # type: ignore[override]
        if self._log_file is not None and item is not None:
            self._tee(item)
        super().put(item, block, timeout)

    def _tee(self, event: object) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        if isinstance(event, LogEvent):
            msg = sanitize_log_message(event.message, self._sensitive_keys)
            line = f"[{ts}] {event.level.value.upper()}: {msg}"
        elif isinstance(event, ProgressEvent):
            line = f"[{ts}] PROGRESS: {event.stage}: {event.message}"
        elif isinstance(event, ErrorEvent):
            msg = sanitize_log_message(event.message, self._sensitive_keys)
            line = f"[{ts}] ERROR: {msg}"
        else:
            return
        try:
            self._log_file.write(line + "\n")  # type: ignore[union-attr]
            self._log_file.flush()
        except OSError:
            pass


# Matches script_gen.py's own word-count tolerance — used here to decide whether the
# completion message needs to warn the user that the delivered video will run shorter
# (or longer) than the duration they requested.
_DURATION_MISMATCH_TOLERANCE = 0.10


def _duration_mismatch_message(script: str, duration_minutes: int) -> str | None:
    """Return a user-facing note if *script*'s word count misses the requested duration
    by more than the tolerance, or None if it's close enough."""
    target_words = duration_minutes * DEFAULT_WPM
    if not target_words:
        return None
    actual_words = len(script.split())
    deviation = abs(actual_words - target_words) / target_words
    if deviation <= _DURATION_MISMATCH_TOLERANCE:
        return None
    actual_minutes = round(actual_words / DEFAULT_WPM)
    direction = "fell short of" if actual_words < target_words else "exceeded"
    return (
        f"Video generated is approximately {actual_minutes} min vs the "
        f"{duration_minutes} min requested (script word count {direction} target)."
    )


class RunMode(str, Enum):
    GUIDED = "guided"
    FULL_AUTO = "full_auto"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PipelineRunner(threading.Thread):
    def __init__(
        self,
        topic: str,
        duration_minutes: int,
        mode: RunMode,
        llm: LLMProvider,
        tts: TTSProvider,
        footage_providers: list[FootageProvider],
        output_base: Path,
        topic_source: TopicSource = "user_supplied",
        sensitive_keys: list[str] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="PipelineRunner")
        self.topic = topic
        self.duration_minutes = duration_minutes
        self.mode = mode
        self.llm = llm
        self.tts = tts
        self.footage_providers = footage_providers
        self.output_base = output_base
        self.topic_source: TopicSource = topic_source
        self._sensitive_keys: list[str] = sensitive_keys or []

        self.event_queue: _TeeQueue = _TeeQueue()
        self.cancel_event = threading.Event()

        self._status = RunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = RunStatus.FAILED
        finally:
            self._save_history()
            self.event_queue.close_log()  # flush log before sentinel
            self.event_queue.put(None)  # sentinel for queue drainer

    def _execute(self) -> None:
        # Stage 0: Full Auto topic discovery (deferred to Phase 4 / US2)
        if self.mode == RunMode.FULL_AUTO:
            from docu_studio.pipeline.stages import topic_discovery
            result = topic_discovery.run(self.llm, self.event_queue)
            self.topic = result.topic
            self.topic_source = result.source  # type: ignore[assignment]

        if self._cancelled():
            return

        self._project_folder = create_project_folder(
            self.topic, self._started_at, self.output_base
        )
        self.event_queue.open_log(
            self._project_folder / "pipeline_log.txt",
            self._sensitive_keys,
        )
        ffmpeg = FFmpegWrapper()

        # Stage 1
        script = script_gen.run(
            self.topic, self.duration_minutes, self.llm, self._project_folder, self.event_queue
        )
        if self._cancelled():
            return

        # Stage 2
        scenes = scene_break.run(script, self.llm, self._project_folder, self.event_queue)
        if self._cancelled():
            return

        # Stage 3
        tts_gen.run(scenes, self.tts, self._project_folder, self.event_queue)
        if self._cancelled():
            return

        # Stage 4
        keyword_extract.run(scenes, self.llm, self.event_queue)
        if self._cancelled():
            return

        # Stages 5+6
        footage_assembly.run(
            scenes, self.footage_providers, ffmpeg, self._project_folder, self.event_queue
        )
        if self._cancelled():
            return

        # Stage 7
        fcpxml_export.run(scenes, self.topic, self._project_folder, self.event_queue)

        # Stage 8: final merge (non-fatal)
        self._final_video_path = final_merge.run(
            scenes, ffmpeg, self._project_folder, self.event_queue
        )

        self._status = RunStatus.COMPLETED
        done_message = "Pipeline completed successfully."
        mismatch = _duration_mismatch_message(script, self.duration_minutes)
        if mismatch:
            done_message = f"{done_message} {mismatch}"
        self.event_queue.put(ProgressEvent(stage="Done", message=done_message))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = RunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic=self.topic,
                mode=self.mode.value,
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source=self.topic_source,
                fallback_triggered=False,
            )
            save_run(record)
        except Exception:
            pass  # history failure must never crash the runner
