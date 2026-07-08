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
from docu_studio.shorts.shorts_cuts import MAX_SEGMENT_DURATION, Segment, choose_crop_strategy, plan_cuts
from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg
from docu_studio.shorts.shorts_script_gen import ShortsScript

_log = logging.getLogger(__name__)

_MIN_CLIPS = 6


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
    searched with min_duration >= MAX_SEGMENT_DURATION so any assigned segment
    always fits inside the downloaded clip. Returns [{path, width, height}, ...]."""
    per_sentence = _search_dedup(providers, script.visual_queries, min_duration=MAX_SEGMENT_DURATION)
    n_needed = max(_MIN_CLIPS, len(script.sentences))

    pool = list(per_sentence)
    if len(pool) < n_needed:
        topic_query = script.visual_queries[0] if script.visual_queries else "documentary footage"
        extra = _search_dedup(providers, [topic_query], min_duration=MAX_SEGMENT_DURATION)
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

    event_queue.put(ProgressEvent(stage="Short Mux", message="Concatenating and muxing final short…"))
    concat_path = str(scene_dir / "short_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)
    ffmpeg.mux_shorts_audio(concat_path, audio_path, str(output_path))

    event_queue.put(LogEvent(
        message=f"Short assembled: {len(segments)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
