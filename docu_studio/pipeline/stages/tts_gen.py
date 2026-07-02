"""Stage 3: Generate per-scene audio via TTSProvider."""
from __future__ import annotations

import queue
from pathlib import Path

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages.scene_break import Scene


def run(
    scenes: list[Scene],
    tts: TTSProvider,
    project_folder: Path,
    event_queue: queue.Queue,
) -> None:
    total = len(scenes)
    for scene in scenes:
        event_queue.put(ProgressEvent(
            stage="TTS Generation",
            scene_index=scene.index,
            scene_total=total,
            message=f"Synthesizing audio for scene {scene.index}: {scene.title}",
        ))
        output_path = str(project_folder / "audio" / f"scene_{scene.index:03d}.mp3")
        duration = tts.synthesize(scene.narration, output_path)
        scene.audio_path = output_path
        scene.audio_duration = duration
        event_queue.put(LogEvent(
            message=f"Scene {scene.index} audio: {duration:.2f}s",
            level=LogLevel.INFO,
        ))
