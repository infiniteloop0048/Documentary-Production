"""Audio-first assembly for Slideshow: TTS duration -> even image split ->
Ken Burns -> hard-cut concat -> mux narration audio over the result.

Deliberately does not use sentence_spans()/word-timing/sentence-scoped pool
assignment — those solve a problem (aligning per-sentence narration to
per-sentence *searched* image results) that doesn't exist yet with a flat,
manually-ordered image list and no topic search. See the Phase 1 design
spec for why this is out of scope here.
"""
from __future__ import annotations

import logging
from pathlib import Path

from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
from docu_studio.slideshow.slideshow_motion import direction_for_index

_log = logging.getLogger(__name__)


def split_duration_evenly(total_duration: float, count: int) -> list[float]:
    """Split *total_duration* into *count* segment durations that sum
    exactly to *total_duration*. All segments get the same duration except
    the last, which absorbs the rounding remainder."""
    if count <= 0:
        raise ValueError("count must be positive")
    base = round(total_duration / count, 3)
    durations = [base] * (count - 1)
    last = round(total_duration - sum(durations), 3)
    durations.append(last)
    return durations


def assemble_slideshow(
    image_paths: list[str],
    audio_path: str,
    audio_duration: float,
    ffmpeg: SlideshowFFmpeg,
    scene_dir: Path,
    output_path: Path,
    out_width: int,
    out_height: int,
    event_queue,
) -> None:
    """Build the final slideshow video: one Ken-Burns segment per image,
    durations evenly splitting *audio_duration*, hard-cut concat, narration
    audio muxed over the result."""
    durations = split_duration_evenly(audio_duration, len(image_paths))

    event_queue.put(ProgressEvent(
        stage="Slideshow Assembly", message=f"Building {len(image_paths)} segments…",
    ))
    segment_paths: list[str] = []
    for i, (image_path, duration) in enumerate(zip(image_paths, durations)):
        direction = direction_for_index(i)
        seg_path = str(scene_dir / f"seg_{i:03d}.mp4")
        try:
            ffmpeg.apply_ken_burns_image(
                image_path, seg_path, duration, direction, out_width, out_height,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Segment {i} (image {image_path!r}) failed to render: {exc}"
            ) from exc
        segment_paths.append(seg_path)
        _log.info(
            "Segment %d: image=%s duration=%.2f direction=%s",
            i, image_path, duration, direction,
        )

    concat_path = str(scene_dir / "slideshow_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)

    event_queue.put(ProgressEvent(stage="Slideshow Mux", message="Muxing final slideshow…"))
    ffmpeg.mux_audio_video(concat_path, audio_path, str(output_path))

    event_queue.put(LogEvent(
        message=f"Slideshow assembled: {len(image_paths)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
