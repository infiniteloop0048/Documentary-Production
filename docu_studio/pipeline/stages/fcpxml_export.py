"""Stage 7: Sync-gate validation then FCPXML write."""
from __future__ import annotations

import queue
from pathlib import Path

from docu_studio.media.fcpxml_generator import (
    ExportSyncError,
    FinalScene,
    generate_fcpxml,
    validate_sync,
)
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages.scene_break import Scene


def run(
    scenes: list[Scene],
    topic: str,
    project_folder: Path,
    event_queue: queue.Queue,
) -> None:
    event_queue.put(ProgressEvent(stage="FCPXML Export", message="Validating sync and exporting timeline…"))

    final_scenes = [
        FinalScene(
            index=s.index,
            title=s.title,
            narration=s.narration,
            audio_path=s.audio_path or "",
            audio_duration=s.audio_duration,
            video_path=s.video_path or "",
            video_duration=s.video_duration,
        )
        for s in scenes
        if s.video_path and not s.footage_shortage
    ]

    if not final_scenes:
        event_queue.put(ErrorEvent(
            message="No scenes with complete footage — FCPXML export skipped.",
            fatal=False,
        ))
        return

    try:
        xml_str = generate_fcpxml(final_scenes, project_folder, topic)
    except ExportSyncError as exc:
        event_queue.put(ErrorEvent(message=f"Sync invariant violated: {exc}", fatal=True))
        raise

    out_path = project_folder / "timeline.fcpxml"
    out_path.write_text(xml_str, encoding="utf-8")
    event_queue.put(LogEvent(
        message=f"FCPXML exported to {out_path.name} ({len(final_scenes)} scenes)",
        level=LogLevel.INFO,
    ))
    event_queue.put(ProgressEvent(stage="FCPXML Export", message="Export complete."))
