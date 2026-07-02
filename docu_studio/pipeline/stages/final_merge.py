"""Stage 8: Concatenate all assembled scene videos into one final_video.mp4."""
from __future__ import annotations

import queue
from pathlib import Path

from docu_studio.media.ffmpeg_wrapper import FFmpegError, FFmpegWrapper
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages.scene_break import Scene


def run(
    scenes: list[Scene],
    ffmpeg: FFmpegWrapper,
    project_folder: Path,
    event_queue: queue.Queue,
) -> Path | None:
    """Merge all assembled scene videos into *project_folder*/final_video.mp4.

    Returns the output Path on success, None if merge was skipped or failed.
    Failure is non-fatal — FCPXML export already succeeded.
    """
    video_paths = [s.video_path for s in scenes if s.video_path and not s.footage_shortage]
    if not video_paths:
        event_queue.put(LogEvent(
            message="Final merge skipped — no assembled scene videos found.",
            level=LogLevel.WARNING,
        ))
        return None

    n = len(video_paths)
    output_path = project_folder / "final_video.mp4"

    event_queue.put(ProgressEvent(stage="Final Merge", message=f"Merging {n} scenes into final_video.mp4…"))
    event_queue.put(LogEvent(
        message=f"Merging {n} scenes into final_video.mp4…",
        level=LogLevel.INFO,
    ))

    try:
        ffmpeg.concat_scenes(video_paths, str(output_path))
        duration = ffmpeg.get_duration(str(output_path))
        event_queue.put(LogEvent(
            message=f"Final video: {duration:.1f}s → {output_path}",
            level=LogLevel.INFO,
        ))
        return output_path
    except (FFmpegError, Exception) as exc:
        event_queue.put(LogEvent(
            message=f"Final merge failed (FCPXML is still valid): {exc}",
            level=LogLevel.WARNING,
        ))
        return None
