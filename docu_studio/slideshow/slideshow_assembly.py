"""Audio-first assembly for Slideshow: TTS duration -> even image split ->
Ken Burns -> concat (hard cut or crossfade) -> overlays -> captions -> mux
narration (+ music) over the result.

Deliberately does not use sentence_spans()/audio-aligned word-timing/
sentence-scoped pool assignment — those solve a problem (aligning per-sentence
narration to per-sentence *searched* image results) that doesn't exist yet
with a flat, manually-ordered image list and no topic search. See the Phase 1
design spec for why this is out of scope here. Phase 3's captions use a
duration-estimate word timing instead (docu_studio.common.captions), which is
a different thing from that deferred sentence-scoped alignment.
"""
from __future__ import annotations

import logging
from pathlib import Path

from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
from docu_studio.slideshow.slideshow_motion import direction_for_index

_log = logging.getLogger(__name__)

_TRANSITION_DURATION = 0.5


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


def crossfade_segment_durations(base_durations: list[float], transition_duration: float) -> list[float]:
    """Inflate every segment except the last by *transition_duration*
    seconds. Chaining N-1 xfade merges each shortens the timeline by
    *transition_duration*, so inflating N-1 of the N segments by that amount
    means the post-crossfade total still equals sum(base_durations) exactly
    — no shrinkage relative to the narration's measured length."""
    if len(base_durations) < 2:
        return list(base_durations)
    return [d + transition_duration for d in base_durations[:-1]] + [base_durations[-1]]


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
    transition: str = "cut",
    vignette: bool = False,
    grain: bool = False,
    captions: bool = False,
    script_text: str = "",
    music_path: str | None = None,
) -> None:
    """Build the final slideshow video. All Phase 3 parameters default to
    Phase 1/2 behavior: hard cut, no overlays, no captions, no music — a
    caller that passes none of them gets the exact prior pipeline."""
    base_durations = split_duration_evenly(audio_duration, len(image_paths))
    use_crossfade = transition == "crossfade" and len(image_paths) > 1
    durations = crossfade_segment_durations(base_durations, _TRANSITION_DURATION) if use_crossfade else base_durations

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
    if use_crossfade:
        ffmpeg.concat_segments_with_xfade(segment_paths, durations, _TRANSITION_DURATION, concat_path)
    else:
        ffmpeg.concat_segments_video_only(segment_paths, concat_path)
    video_path = concat_path

    if vignette or grain:
        overlay_path = str(scene_dir / "slideshow_overlay.mp4")
        ffmpeg.apply_overlays(video_path, overlay_path, vignette, grain)
        video_path = overlay_path

    if captions:
        from docu_studio.common.captions import estimate_word_timestamps, write_ass_file

        timings = estimate_word_timestamps(script_text, audio_duration)
        ass_path = str(scene_dir / "captions.ass")
        write_ass_file(timings, ass_path, out_width, out_height, audio_duration)
        captioned_path = str(scene_dir / "slideshow_captioned.mp4")
        ffmpeg.burn_captions(video_path, ass_path, captioned_path)
        video_path = captioned_path

    event_queue.put(ProgressEvent(stage="Slideshow Mux", message="Muxing final slideshow…"))
    narration_path = audio_path
    if music_path:
        # .m4a, not .mp3: mix_music_bed encodes with -c:a aac, and ffmpeg's
        # mp3 muxer rejects AAC-encoded data written to a .mp3-named output
        # (confirmed by a real pipeline run — the mocked unit tests can't
        # catch a container/codec mismatch since they never execute ffmpeg).
        mixed_audio_path = str(scene_dir / "narration_with_music.m4a")
        ffmpeg.mix_music_bed(audio_path, music_path, audio_duration, mixed_audio_path)
        narration_path = mixed_audio_path
    ffmpeg.mux_audio_video(video_path, narration_path, str(output_path))

    event_queue.put(LogEvent(
        message=f"Slideshow assembled: {len(image_paths)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
