"""Stage 2: Break script into scenes via LLMProvider."""
from __future__ import annotations

import json
import queue
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent


@dataclass
class Scene:
    index: int
    title: str
    narration: str
    visual_keywords: list[str] = field(default_factory=list)
    audio_path: Optional[str] = None
    audio_duration: float = 0.0
    video_path: Optional[str] = None
    video_duration: float = 0.0
    footage_shortage: bool = False


def run(
    script: str,
    llm: LLMProvider,
    project_folder: Path,
    event_queue: queue.Queue,
) -> list[Scene]:
    event_queue.put(ProgressEvent(stage="Scene Breakdown", message="Breaking script into scenes…"))
    raw_scenes = llm.break_into_scenes(script)
    scenes = [
        Scene(index=i + 1, title=s["title"], narration=s["narration"])
        for i, s in enumerate(raw_scenes)
    ]
    scenes_data = [
        {"index": s.index, "title": s.title, "narration": s.narration}
        for s in scenes
    ]
    (project_folder / "scenes.json").write_text(
        json.dumps(scenes_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    event_queue.put(LogEvent(message=f"Script broken into {len(scenes)} scenes", level=LogLevel.INFO))
    return scenes
