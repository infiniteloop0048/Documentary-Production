"""ShortsRunner — background thread that orchestrates the Shorts/Reels pipeline.

Mirrors docu_studio.pipeline.runner.PipelineRunner's public shape (event_queue,
cancel_event, _final_video_path, _project_folder, run()) so the existing
Bridge._translate_events() works unmodified for both run types. Does not import
from pipeline.runner — ShortsTeeQueue (shorts_log.py) is a parallel
implementation of pipeline.runner._TeeQueue used here for per-run
shorts_log.txt teeing; project folder + history integration are reused.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.shorts.capability_resolvers import get_word_timestamps
from docu_studio.shorts.shorts_assembly import assemble_short
from docu_studio.shorts.shorts_config import ShortsConfig
from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg
from docu_studio.shorts.shorts_log import QueueLoggingHandler, ShortsTeeQueue
from docu_studio.shorts.shorts_script_gen import generate_shorts_script


class ShortsRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ShortsRunner(threading.Thread):
    def __init__(
        self,
        topic: str,
        duration_seconds: int,
        llm: LLMProvider,
        tts: TTSProvider,
        footage_providers: list[FootageProvider],
        output_base: Path,
        captions_enabled: bool = True,
        music_enabled: bool = True,
        sensitive_keys: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        super().__init__(daemon=True, name="ShortsRunner")
        self.config = ShortsConfig(
            topic=topic,
            duration_seconds=duration_seconds,
            captions_enabled=captions_enabled,
            music_enabled=music_enabled,
        )
        self.llm = llm
        self.tts = tts
        self.footage_providers = footage_providers
        self.output_base = output_base
        self._sensitive_keys: list[str] = sensitive_keys or []
        self._seed = seed if seed is not None else int(datetime.now().timestamp())

        self.event_queue: ShortsTeeQueue = ShortsTeeQueue()
        self.cancel_event = threading.Event()

        self._status = ShortsRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        shorts_logger = logging.getLogger("docu_studio.shorts")
        handler = QueueLoggingHandler(self.event_queue)
        prev_level = shorts_logger.level
        shorts_logger.addHandler(handler)
        shorts_logger.setLevel(logging.INFO)
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = ShortsRunStatus.FAILED
        finally:
            shorts_logger.removeHandler(handler)
            shorts_logger.setLevel(prev_level)
            self._save_history()
            self.event_queue.close_log()  # flush log before sentinel
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        self._project_folder = create_project_folder(
            self.config.topic, self._started_at, self.output_base
        )
        self.event_queue.open_log(
            self._project_folder / "shorts_log.txt", self._sensitive_keys
        )
        ffmpeg = ShortsFFmpeg()

        self.event_queue.put(ProgressEvent(
            stage="Short Script", message=f"Writing short script for '{self.config.topic}'…",
        ))
        script = generate_shorts_script(self.config.topic, self.config.duration_seconds, self.llm)
        (self._project_folder / "script.md").write_text(script.text, encoding="utf-8")
        self.event_queue.put(LogEvent(
            message=f"Short script generated ({len(script.text.split())} words, "
                    f"{len(script.sentences)} sentences)",
            level=LogLevel.INFO,
        ))
        if self._cancelled():
            return

        self.event_queue.put(ProgressEvent(stage="Short TTS", message="Synthesizing voiceover…"))
        audio_path = str(self._project_folder / "audio" / "short.mp3")
        audio_duration = self.tts.synthesize(script.text, audio_path)
        self.event_queue.put(LogEvent(message=f"Voiceover: {audio_duration:.2f}s", level=LogLevel.INFO))
        if self._cancelled():
            return

        self.event_queue.put(ProgressEvent(
            stage="Short Alignment", message="Resolving word-level timing…",
        ))
        timestamps, tier_used = get_word_timestamps(audio_path, script.text, self.tts)
        self.event_queue.put(LogEvent(message=f"Word timing resolver: {tier_used}", level=LogLevel.INFO))
        if self._cancelled():
            return

        output_path = self._project_folder / "short_final.mp4"
        assemble_short(
            script=script,
            audio_path=audio_path,
            audio_duration=audio_duration,
            timestamps=timestamps,
            tier_used=tier_used,
            providers=self.footage_providers,
            ffmpeg=ffmpeg,
            project_folder=self._project_folder,
            output_path=output_path,
            seed=self._seed,
            event_queue=self.event_queue,
            captions_enabled=self.config.captions_enabled,
            music_enabled=self.config.music_enabled,
        )
        if self._cancelled():
            return

        self._final_video_path = output_path
        self._status = ShortsRunStatus.COMPLETED
        actual_duration = ffmpeg.get_duration(str(output_path))
        self.event_queue.put(ProgressEvent(
            stage="Done",
            message=(
                f"Short completed: {actual_duration:.1f}s actual vs "
                f"{self.config.duration_seconds}s requested."
            ),
        ))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = ShortsRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic=self.config.topic,
                mode="shorts",
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source="user_supplied",
                fallback_triggered=False,
            )
            save_run(record)
        except Exception:
            pass  # history failure must never crash the runner
