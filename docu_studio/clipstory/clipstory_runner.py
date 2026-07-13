"""ClipStoryRunner: threading.Thread orchestrator mirroring ShortsRunner's shape
(event_queue, cancel_event, _project_folder, _final_video_path) so Bridge's
existing event-translation code works unmodified for the new 'clipstory' mode.
"""
from __future__ import annotations

import queue
import tempfile
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.clipstory.clipstory_assembly import ClipStoryFitError, assemble_clip_story
from docu_studio.clipstory.clipstory_config import ClipStoryConfig
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, ProgressEvent


class ClipStoryRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ClipStoryRunner(threading.Thread):
    def __init__(self, config: ClipStoryConfig, tts: TTSProvider, output_base: Path) -> None:
        super().__init__(daemon=True, name="ClipStoryRunner")
        self.config = config
        self.tts = tts
        self.output_base = output_base
        self.event_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self._status = ClipStoryRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        try:
            self._execute()
        except ClipStoryFitError as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
        finally:
            self._save_history()
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        self._project_folder = create_project_folder(
            self.config.topic, self._started_at, self.output_base
        )
        self.event_queue.put(ProgressEvent(stage="ClipStory Assembly", message="Assembling clips…"))
        with tempfile.TemporaryDirectory(prefix="docu_studio_clipstory_") as tmp:
            if self._cancelled():
                return
            output_path = self._project_folder / "clipstory_final.mp4"
            assemble_clip_story(
                self.config, self.tts, Path(tmp), output_path, cancel_event=self.cancel_event
            )
            if self._cancelled():
                return
            self._final_video_path = output_path
        self._status = ClipStoryRunStatus.COMPLETED
        self.event_queue.put(ProgressEvent(stage="Done", message="Clip Story completed."))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = ClipStoryRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            save_run(RunRecord(
                topic=self.config.topic,
                mode="clipstory",
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source="user_supplied",
                fallback_triggered=False,
            ))
        except Exception:
            pass
