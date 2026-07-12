"""SlideshowRunner — background thread that orchestrates the Slideshow
pipeline.

Mirrors ShortsRunner's public shape (event_queue, cancel_event,
_final_video_path, _project_folder, run()) so Bridge._translate_events()
works unmodified for slideshow runs — a new branch is added alongside
start_shorts_run, not into it. Does not import anything from
docu_studio.shorts, per the Phase 1 design decision to defer all shared
infrastructure extraction until a later phase actually needs it.
"""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.slideshow.slideshow_assembly import assemble_slideshow
from docu_studio.slideshow.slideshow_config import SlideshowConfig
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
from docu_studio.slideshow.slideshow_images import validate_manual_images
from docu_studio.slideshow.slideshow_music import DEFAULT_MUSIC_MOOD, resolve_music_track


class SlideshowRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SlideshowRunner(threading.Thread):
    def __init__(
        self,
        script_text: str,
        image_paths: list[str],
        tts: TTSProvider,
        output_base: Path,
        aspect_ratio: str = "9:16",
        transition: str = "cut",
        vignette: bool = False,
        grain: bool = False,
        captions: bool = False,
        music_enabled: bool = False,
        music_provider: str = "jamendo",
        music_folder: str = "",
        jamendo_client_id: str = "",
    ) -> None:
        super().__init__(daemon=True, name="SlideshowRunner")
        self.config = SlideshowConfig(
            script_text=script_text, image_paths=image_paths, aspect_ratio=aspect_ratio,
            transition=transition, vignette=vignette, grain=grain, captions=captions,
            music_enabled=music_enabled, music_provider=music_provider,
            music_folder=music_folder, jamendo_client_id=jamendo_client_id,
        )
        self.tts = tts
        self.output_base = output_base

        self.event_queue: "queue.Queue[object]" = queue.Queue()
        self.cancel_event = threading.Event()

        self._status = SlideshowRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = SlideshowRunStatus.FAILED
        finally:
            self._save_history()
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        images = validate_manual_images(self.config.image_paths)
        self._project_folder = create_project_folder(
            "slideshow", self._started_at, self.output_base
        )
        ffmpeg = SlideshowFFmpeg()

        self.event_queue.put(ProgressEvent(
            stage="Slideshow TTS", message="Synthesizing narration…",
        ))
        audio_path = str(self._project_folder / "audio" / "narration.mp3")
        audio_duration = self.tts.synthesize(self.config.script_text, audio_path)
        self.event_queue.put(LogEvent(
            message=f"Narration: {audio_duration:.2f}s", level=LogLevel.INFO,
        ))
        if self._cancelled():
            return

        music_path = None
        if self.config.music_enabled:
            resolved = resolve_music_track(
                provider_name=self.config.music_provider,
                mood=DEFAULT_MUSIC_MOOD,
                max_duration=audio_duration,
                jamendo_client_id=self.config.jamendo_client_id,
                local_folder=self.config.music_folder,
            )
            if resolved:
                music_path, music_label = resolved
                self.event_queue.put(LogEvent(
                    message=f"Music: using {music_label!r}", level=LogLevel.INFO,
                ))
            else:
                self.event_queue.put(LogEvent(
                    message="Music: no usable track found — continuing without music bed",
                    level=LogLevel.INFO,
                ))
        if self._cancelled():
            return

        out_width, out_height = self.config.output_dimensions
        output_path = self._project_folder / "slideshow_final.mp4"
        assemble_slideshow(
            image_paths=images,
            audio_path=audio_path,
            audio_duration=audio_duration,
            ffmpeg=ffmpeg,
            scene_dir=self._project_folder / "video",
            output_path=output_path,
            out_width=out_width,
            out_height=out_height,
            event_queue=self.event_queue,
            transition=self.config.transition,
            vignette=self.config.vignette,
            grain=self.config.grain,
            captions=self.config.captions,
            script_text=self.config.script_text,
            music_path=music_path,
        )
        if self._cancelled():
            return

        self._final_video_path = output_path
        self._status = SlideshowRunStatus.COMPLETED
        self.event_queue.put(ProgressEvent(
            stage="Done", message=f"Slideshow completed: {output_path}",
        ))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = SlideshowRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic="Slideshow",
                mode="slideshow",
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source="user_supplied",
                fallback_triggered=False,
            )
            save_run(record)
        except Exception:
            pass  # history failure must never crash the runner
