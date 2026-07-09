"""Audio-first assembly for Shorts/Reels: footage fetch, windowing, vertical
conversion, Ken Burns, concat + mux — keyed off the measured TTS audio duration.
"""
from __future__ import annotations

import logging
import queue
from pathlib import Path

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages.footage_assembly import download_clip
from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_cuts import (
    MAX_SEGMENT_DURATION,
    MIN_SEGMENT_DURATION,
    Segment,
    choose_crop_strategy,
    plan_cuts,
)
from docu_studio.shorts.music_providers import resolve_music_track
from docu_studio.shorts.shorts_captions import write_ass_file
from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg
from docu_studio.shorts.shorts_script_gen import ShortsScript

_log = logging.getLogger(__name__)

_MIN_CLIPS = 6

# plan_cuts' final segment can require up to MIN_SEGMENT_DURATION + MAX_SEGMENT_DURATION
# (it's trimmed to land exactly on the audio end) — every downloaded clip must be at
# least that long, since plan_cuts assigns clips to segments round-robin and any clip
# can land on the final one.
_MIN_CLIP_DURATION = MIN_SEGMENT_DURATION + MAX_SEGMENT_DURATION

_SLOW_CLIP_MIN_SOURCE_DURATION = 15.0
SPEED_RAMP_FACTOR = 1.35
_MIN_SPEED_FACTOR = 1.25
_LOOP_REVISIT_MIN_GAP = 1.0


def _search_dedup(
    providers: list[FootageProvider], queries: list[str], min_duration: float,
) -> list[tuple[str, int, int]]:
    """Search *providers* for each query in *queries*; return deduped
    (url, width, height) tuples in first-seen order."""
    seen: dict[str, tuple[str, int, int]] = {}
    for query in queries:
        for provider in providers:
            try:
                clips = provider.search([query], min_duration=min_duration, page=1)
            except Exception:
                continue
            for clip in clips:
                if clip.url not in seen:
                    seen[clip.url] = (clip.url, clip.width, clip.height)
            if clips:
                break
    return list(seen.values())


def _collect_clips(
    script: ShortsScript, providers: list[FootageProvider], scene_dir: Path,
    event_queue: queue.Queue,
) -> list[dict]:
    """Fetch and download clips for the per-sentence queries, deduped, padded to at
    least _MIN_CLIPS using the topic-level (first) query if short. Every clip is
    searched with min_duration >= _MIN_CLIP_DURATION so any assigned segment —
    including a worst-case final segment — always fits inside the downloaded clip.
    Returns [{path, width, height}, ...]."""
    per_sentence = _search_dedup(providers, script.visual_queries, min_duration=_MIN_CLIP_DURATION)
    n_needed = max(_MIN_CLIPS, len(script.sentences))

    pool = list(per_sentence)
    if len(pool) < n_needed:
        topic_query = script.visual_queries[0] if script.visual_queries else "documentary footage"
        extra = _search_dedup(providers, [topic_query], min_duration=_MIN_CLIP_DURATION)
        existing_urls = {p[0] for p in pool}
        for item in extra:
            if item[0] not in existing_urls:
                pool.append(item)
                existing_urls.add(item[0])
            if len(pool) >= n_needed:
                break

    if not pool:
        raise RuntimeError("Shorts assembly: no footage found for any query.")

    downloaded: list[dict] = []
    for i, (url, width, height) in enumerate(pool):
        dest = str(scene_dir / f"short_clip_{i:03d}.mp4")
        try:
            download_clip(url, dest)
        except Exception:
            continue
        downloaded.append({"path": dest, "width": width, "height": height})

    if not downloaded:
        raise RuntimeError("Shorts assembly: all footage downloads failed.")

    event_queue.put(LogEvent(
        message=f"Shorts footage: {len(downloaded)} clips downloaded (target {n_needed})",
        level=LogLevel.INFO,
    ))
    return downloaded


def _sentence_start_times(script: ShortsScript, timestamps: list[WordTiming]) -> list[float]:
    """Return the start time of each sentence's first word, given a flat *timestamps*
    list aligned word-for-word to the concatenation of *script.sentences*."""
    starts: list[float] = []
    cursor = 0
    for sentence in script.sentences:
        word_count = len(sentence.split())
        if cursor >= len(timestamps) or word_count == 0:
            break
        starts.append(timestamps[cursor].start)
        cursor += word_count
    return starts


def _snap_to_sentences(segments: list[Segment], sentence_starts: list[float]) -> list[Segment]:
    if not sentence_starts:
        return segments
    snapped = []
    for seg in segments:
        nearest = min(sentence_starts, key=lambda t: abs(t - seg.start))
        snapped.append(Segment(index=seg.index, start=nearest, duration=seg.duration, clip_index=seg.clip_index))
    return snapped


def _build_segment(
    seg: Segment,
    clip: dict,
    ffmpeg: ShortsFFmpeg,
    scene_dir: Path,
    speed_ramp_enabled: bool,
    sped_count: int,
    max_sped_segments: int,
    avoid_start: float | None = None,
) -> tuple[str, int, float]:
    """Build one footage segment: window/trim (+ optional speed ramp for a
    slow, long-source clip) -> vertical convert -> Ken Burns.

    *avoid_start* is set only for the loop-revisit segment: when given, and
    the source clip is long enough to offer a distinct window, the motion-
    detected start is swapped for a window from the opposite end of the
    clip so the revisit doesn't just replay the exact same window as the
    original first segment. Otherwise (source too short) the same window
    is kept, per spec.

    Returns (kenburns_output_path, updated_sped_count, window_start_used).
    """
    raw_duration = ffmpeg.get_duration(clip["path"])
    window = min(seg.duration, raw_duration)
    start, method = ffmpeg.detect_motion_window(clip["path"], raw_duration, window)
    _log.info(
        "Segment %d: clip=%s window_method=%s start=%.2f",
        seg.index, clip["path"], method, start,
    )

    if avoid_start is not None and raw_duration - window >= _LOOP_REVISIT_MIN_GAP:
        alt_start = max(0.0, raw_duration - window)
        if abs(alt_start - avoid_start) >= _LOOP_REVISIT_MIN_GAP:
            start = alt_start
            method = "loop_revisit_alt_window"
            _log.info("Segment %d: loop-revisit using alternate window start=%.2f", seg.index, start)

    is_slow_candidate = method == "fallback" and raw_duration >= _SLOW_CLIP_MIN_SOURCE_DURATION
    apply_speed = (
        speed_ramp_enabled and is_slow_candidate
        and not seg.loop_revisit and sped_count < max_sped_segments
    )
    if apply_speed:
        source_trim = min(seg.duration * SPEED_RAMP_FACTOR, max(0.0, raw_duration - start))
        if source_trim < seg.duration * _MIN_SPEED_FACTOR:
            apply_speed = False  # not enough source to speed ramp meaningfully

    if apply_speed:
        trim_duration = source_trim
        output_duration = seg.duration
    else:
        trim_duration = min(seg.duration, max(0.0, raw_duration - start))
        output_duration = trim_duration
        if trim_duration < seg.duration:
            _log.warning(
                "Segment %d: clip %s only has %.2fs remaining from start=%.2f, "
                "needed %.2fs (shortfall %.2fs)",
                seg.index, clip["path"], trim_duration, start, seg.duration,
                seg.duration - trim_duration,
            )

    windowed = str(scene_dir / f"seg_{seg.index:03d}_window.mp4")
    ffmpeg.trim_clip(clip["path"], start, trim_duration, windowed)

    if apply_speed:
        actual_factor = trim_duration / seg.duration
        sped = str(scene_dir / f"seg_{seg.index:03d}_sped.mp4")
        ffmpeg.apply_speed_ramp(windowed, sped, actual_factor)
        windowed = sped
        sped_count += 1
        _log.info("Segment %d: sped up (factor=%.2f)", seg.index, actual_factor)
    else:
        _log.info("Segment %d: not sped up", seg.index)

    strategy = choose_crop_strategy(clip["width"], clip["height"])
    vertical = str(scene_dir / f"seg_{seg.index:03d}_vertical.mp4")
    ffmpeg.vertical_convert(windowed, vertical, strategy)
    _log.info("Segment %d: crop_strategy=%s", seg.index, strategy)

    direction = "in" if seg.index % 2 == 0 else "out"
    pan = seg.index % 3 == 0
    kenburns = str(scene_dir / f"seg_{seg.index:03d}_kb.mp4")
    ffmpeg.apply_ken_burns(vertical, kenburns, output_duration, direction, pan)

    return kenburns, sped_count, start


def assemble_short(
    script: ShortsScript,
    audio_path: str,
    audio_duration: float,
    timestamps: list[WordTiming],
    tier_used: str,
    providers: list[FootageProvider],
    ffmpeg: ShortsFFmpeg,
    project_folder: Path,
    output_path: Path,
    seed: int,
    event_queue: queue.Queue,
    captions_enabled: bool = True,
    music_enabled: bool = True,
    music_provider: str = "local",
    jamendo_client_id: str = "",
) -> None:
    """Build the final vertical short: fetch footage, plan cuts, window/convert/
    Ken-Burns each segment, concat, and mux with the TTS audio track."""
    scene_dir = project_folder / "video"
    scene_dir.mkdir(exist_ok=True)

    event_queue.put(ProgressEvent(stage="Short Footage", message="Searching stock footage…"))
    clips = _collect_clips(script, providers, scene_dir, event_queue)

    segments = plan_cuts(total_duration=audio_duration, n_clips=len(clips), seed=seed)
    if tier_used == "tier1_native":
        sentence_starts = _sentence_start_times(script, timestamps)
        segments = _snap_to_sentences(segments, sentence_starts)

    event_queue.put(ProgressEvent(stage="Short Assembly", message=f"Building {len(segments)} segments…"))

    segment_paths: list[str] = []
    for seg in segments:
        clip = clips[seg.clip_index]
        raw_duration = ffmpeg.get_duration(clip["path"])
        window = min(seg.duration, raw_duration)
        start, method = ffmpeg.detect_motion_window(clip["path"], raw_duration, window)
        _log.info(
            "Segment %d: clip=%s window_method=%s start=%.2f",
            seg.index, clip["path"], method, start,
        )

        trim_duration = min(seg.duration, max(0.0, raw_duration - start))
        if trim_duration < seg.duration:
            _log.warning(
                "Segment %d: clip %s only has %.2fs remaining from start=%.2f, "
                "needed %.2fs (shortfall %.2fs)",
                seg.index, clip["path"], trim_duration, start, seg.duration,
                seg.duration - trim_duration,
            )

        windowed = str(scene_dir / f"seg_{seg.index:03d}_window.mp4")
        ffmpeg.trim_clip(clip["path"], start, trim_duration, windowed)

        strategy = choose_crop_strategy(clip["width"], clip["height"])
        vertical = str(scene_dir / f"seg_{seg.index:03d}_vertical.mp4")
        ffmpeg.vertical_convert(windowed, vertical, strategy)
        _log.info("Segment %d: crop_strategy=%s", seg.index, strategy)

        direction = "in" if seg.index % 2 == 0 else "out"
        pan = seg.index % 3 == 0
        kenburns = str(scene_dir / f"seg_{seg.index:03d}_kb.mp4")
        ffmpeg.apply_ken_burns(vertical, kenburns, trim_duration, direction, pan)

        segment_paths.append(kenburns)

    concat_path = str(scene_dir / "short_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)

    event_queue.put(ProgressEvent(
        stage="Short Captions & Music", message="Adding captions and music bed…",
    ))
    video_for_mux = concat_path
    if captions_enabled:
        try:
            ass_path = str(scene_dir / "captions.ass")
            write_ass_file(timestamps, ass_path, audio_duration=audio_duration)
            captioned_path = str(scene_dir / "short_captioned.mp4")
            ffmpeg.burn_captions(video_for_mux, ass_path, captioned_path)
            video_for_mux = captioned_path
            event_queue.put(LogEvent(message="Captions burned in.", level=LogLevel.INFO))
        except Exception as exc:
            event_queue.put(LogEvent(
                message=f"Captions failed ({exc}) — continuing without captions.",
                level=LogLevel.WARNING,
            ))

    audio_for_mux = audio_path
    if music_enabled:
        try:
            resolved = resolve_music_track(
                music_provider,
                mood=script.music_mood,
                max_duration=audio_duration,
                jamendo_client_id=jamendo_client_id,
                seed=seed,
            )
            if resolved is None:
                event_queue.put(LogEvent(
                    message="No usable music track found — skipping music bed.",
                    level=LogLevel.INFO,
                ))
            else:
                music_path, track_label, _track_bpm = resolved
                mixed_audio = str(scene_dir / "audio_mixed.m4a")
                ffmpeg.mix_music_bed(audio_path, music_path, audio_duration, mixed_audio)
                audio_for_mux = mixed_audio
                event_queue.put(LogEvent(
                    message=f"Music bed mixed in ({track_label}, provider={music_provider}, "
                            f"mood={script.music_mood}).",
                    level=LogLevel.INFO,
                ))
        except Exception as exc:
            event_queue.put(LogEvent(
                message=f"Music mixing failed ({exc}) — continuing without music.",
                level=LogLevel.WARNING,
            ))

    event_queue.put(ProgressEvent(stage="Short Mux", message="Muxing final short…"))
    ffmpeg.mux_shorts_audio(video_for_mux, audio_for_mux, str(output_path))

    event_queue.put(LogEvent(
        message=f"Short assembled: {len(segments)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
