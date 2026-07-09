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
from docu_studio.shorts.capability_resolvers import WordTiming, resolve_beat_grid
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
PUNCH_CARD_DURATION_SECONDS = 1.0
_PUNCH_CARD_MIN_DURATION = 0.8
_MIN_PUNCH_REMAINDER = 0.3


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
        snapped.append(Segment(
            index=seg.index, start=nearest, duration=seg.duration, clip_index=seg.clip_index,
            loop_revisit=seg.loop_revisit, is_punch=seg.is_punch, punch_text=seg.punch_text,
        ))
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


def _insert_punch_card(
    segments: list[Segment],
    punch: tuple[int, str],
    sentence_starts: list[float],
) -> tuple[list[Segment], tuple[float, float] | None]:
    """Insert a punch-card Segment near *punch*'s sentence start, stealing
    its duration from the nearest non-revisit footage segment so total
    timeline length is unchanged. Returns (segments, (card_start, card_end))
    on success, or (segments unchanged, None) if placement isn't possible
    (out-of-range sentence index, no footage segments, or the nearest
    segment is too short to steal PUNCH_CARD_DURATION_SECONDS from)."""
    sentence_index, punch_text = punch
    if sentence_index >= len(sentence_starts):
        return segments, None
    card_time = sentence_starts[sentence_index]

    footage_segments = [s for s in segments if not s.loop_revisit]
    if not footage_segments:
        return segments, None
    target = min(footage_segments, key=lambda s: abs(s.start - card_time))

    card_duration = min(PUNCH_CARD_DURATION_SECONDS, target.duration - _MIN_PUNCH_REMAINDER)
    if card_duration < _PUNCH_CARD_MIN_DURATION:
        return segments, None  # target too short to steal a usable card from — skip

    steal_from_start = target.index != 0
    if steal_from_start:
        card_start = target.start
        new_target = Segment(
            index=target.index, start=target.start + card_duration,
            duration=target.duration - card_duration, clip_index=target.clip_index,
        )
    else:
        card_start = target.start + target.duration - card_duration
        new_target = Segment(
            index=target.index, start=target.start,
            duration=target.duration - card_duration, clip_index=target.clip_index,
        )

    card_segment = Segment(
        index=target.index, start=card_start, duration=card_duration,
        clip_index=0, is_punch=True, punch_text=punch_text,
    )

    new_segments: list[Segment] = []
    for s in segments:
        if s is target:
            if steal_from_start:
                new_segments.append(card_segment)
                new_segments.append(new_target)
            else:
                new_segments.append(new_target)
                new_segments.append(card_segment)
        else:
            new_segments.append(s)

    reindexed = [
        Segment(
            index=i, start=s.start, duration=s.duration, clip_index=s.clip_index,
            loop_revisit=s.loop_revisit, is_punch=s.is_punch, punch_text=s.punch_text,
        )
        for i, s in enumerate(new_segments)
    ]
    return reindexed, (card_start, card_start + card_duration)


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
    beat_sync_enabled: bool = True,
    speed_ramp_enabled: bool = True,
    punch_enabled: bool = True,
    loop_revisit_enabled: bool = True,
) -> None:
    """Build the final vertical short: fetch footage, resolve music (early,
    so its bpm is available for beat-sync), plan cuts, window/convert/
    Ken-Burns each segment (with optional speed ramp and loop-revisit
    alternate window), insert an optional punch card, concat, caption, mix,
    and mux with the TTS audio track. Every optional feature degrades
    silently to prior behavior on failure — this function never raises for
    a feature-specific error."""
    scene_dir = project_folder / "video"
    scene_dir.mkdir(exist_ok=True)

    event_queue.put(ProgressEvent(stage="Short Footage", message="Searching stock footage…"))
    clips = _collect_clips(script, providers, scene_dir, event_queue)

    music_path: str | None = None
    track_label = ""
    track_bpm: int | None = None
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
                music_path, track_label, track_bpm = resolved
        except Exception as exc:
            event_queue.put(LogEvent(
                message=f"Music resolution failed ({exc}) — continuing without music.",
                level=LogLevel.WARNING,
            ))

    beat_grid: list[float] | None = None
    if beat_sync_enabled and music_path:
        try:
            beat_grid, beat_tier = resolve_beat_grid(music_path, track_bpm, audio_duration)
            event_queue.put(LogEvent(
                message=f"Beat grid: tier={beat_tier}"
                        + (f" ({len(beat_grid)} beats)" if beat_grid else ""),
                level=LogLevel.INFO,
            ))
        except Exception as exc:
            event_queue.put(LogEvent(
                message=f"Beat grid resolution failed ({exc}) — cuts unaffected.",
                level=LogLevel.WARNING,
            ))

    segments = plan_cuts(
        total_duration=audio_duration, n_clips=len(clips), seed=seed,
        beat_grid=beat_grid, loop_revisit=loop_revisit_enabled,
    )
    if tier_used == "tier1_native":
        segments = _snap_to_sentences(segments, _sentence_start_times(script, timestamps))

    punch_window: tuple[float, float] | None = None
    # (segment_index, rendered_path) of a punch card already rendered here, at plan-
    # commit time — so the assembly loop below just reuses the file instead of
    # re-rendering (and risking a second, later, unrecoverable failure that would
    # truncate the final narration audio; see Task 12 review Finding 3).
    prerendered_punch: tuple[int, str] | None = None
    if punch_enabled and script.punch is not None:
        try:
            sentence_starts = _sentence_start_times(script, timestamps)
            new_segments, window = _insert_punch_card(segments, script.punch, sentence_starts)
            if window is not None:
                punch_index = next(i for i, s in enumerate(new_segments) if s.is_punch)
                punch_duration = window[1] - window[0]
                rendered_path = str(scene_dir / f"seg_{punch_index:03d}_punch.mp4")
                ffmpeg.generate_punch_card(rendered_path, script.punch[1], punch_duration)
                segments = new_segments
                punch_window = window
                prerendered_punch = (punch_index, rendered_path)
                event_queue.put(LogEvent(
                    message=f"Punch card inserted: {script.punch[1]!r} at {window[0]:.2f}s",
                    level=LogLevel.INFO,
                ))
            else:
                event_queue.put(LogEvent(
                    message="Punch card requested but could not be placed — skipping.",
                    level=LogLevel.INFO,
                ))
        except Exception as exc:
            event_queue.put(LogEvent(
                message=f"Punch card failed ({exc}) — continuing without it.",
                level=LogLevel.WARNING,
            ))

    event_queue.put(ProgressEvent(stage="Short Assembly", message=f"Building {len(segments)} segments…"))

    segment_paths: list[str] = []
    sped_count = 0
    max_sped_segments = len(segments) // 2
    first_window_start: float | None = None
    for seg in segments:
        if seg.is_punch:
            if prerendered_punch is not None and prerendered_punch[0] == seg.index:
                segment_paths.append(prerendered_punch[1])
                _log.info("Segment %d: using pre-rendered punch card %r", seg.index, seg.punch_text)
            else:
                _log.warning(
                    "Segment %d: punch card flagged but no pre-rendered file available — dropping",
                    seg.index,
                )
            continue
        clip = clips[seg.clip_index]
        avoid_start = first_window_start if seg.loop_revisit else None
        try:
            path, sped_count, window_start = _build_segment(
                seg, clip, ffmpeg, scene_dir, speed_ramp_enabled, sped_count, max_sped_segments,
                avoid_start=avoid_start,
            )
        except Exception as exc:
            _log.warning(
                "Segment %d: build with speed-ramp/loop-revisit failed (%s) — retrying plain",
                seg.index, exc,
            )
            path, sped_count, window_start = _build_segment(
                seg, clip, ffmpeg, scene_dir, False, sped_count, max_sped_segments,
                avoid_start=None,
            )
        if seg.index == 0:
            first_window_start = window_start
        segment_paths.append(path)

    concat_path = str(scene_dir / "short_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)

    event_queue.put(ProgressEvent(
        stage="Short Captions & Music", message="Adding captions and music bed…",
    ))
    video_for_mux = concat_path
    if captions_enabled:
        try:
            ass_path = str(scene_dir / "captions.ass")
            write_ass_file(
                timestamps, ass_path, audio_duration=audio_duration, punch_window=punch_window,
            )
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
    if music_path:
        try:
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
