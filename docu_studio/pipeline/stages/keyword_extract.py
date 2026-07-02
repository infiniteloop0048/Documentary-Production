"""Stage 4: Extract per-scene visual keywords via LLMProvider."""
from __future__ import annotations

import queue

from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages.scene_break import Scene


def run(
    scenes: list[Scene],
    llm: LLMProvider,
    event_queue: queue.Queue,
) -> None:
    total = len(scenes)
    for scene in scenes:
        event_queue.put(ProgressEvent(
            stage="Keyword Extraction",
            scene_index=scene.index,
            scene_total=total,
            message=f"Extracting keywords for scene {scene.index}: {scene.title}",
        ))
        keywords = llm.extract_visual_keywords(scene.title, scene.narration)
        if not keywords:
            event_queue.put(LogEvent(
                message=f"WARNING: Scene {scene.index} returned empty keywords — using title as fallback",
                level=LogLevel.WARNING,
            ))
            keywords = [scene.title]
        scene.visual_keywords = keywords
        event_queue.put(LogEvent(
            message=f"Scene {scene.index} keywords: {', '.join(keywords)}",
            level=LogLevel.INFO,
        ))
