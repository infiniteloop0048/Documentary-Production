"""Stage 5+6: Per-scene footage search, trim/concat, and audio/video mux."""
from __future__ import annotations

import logging
import queue
from pathlib import Path

import requests

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages.scene_break import Scene

_DOWNLOAD_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DocuStudio/1.0)"}
_log = logging.getLogger(__name__)


def _provider_name(p: FootageProvider) -> str:
    return type(p).__name__.removesuffix("Adapter")


def download_clip(url: str, dest: str) -> str:
    """Download *url* to *dest* and return *dest*."""
    with requests.get(url, headers=_DOWNLOAD_HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
    return dest


def _collect_from_providers(
    providers: list[FootageProvider],
    keywords: list[str],
    page: int,
    collected: list[str],
    collected_duration: float,
    audio_duration: float,
    scene_dir: Path,
    scene_index: int,
    ffmpeg: FFmpegWrapper,
    clip_sources: dict[str, str],
) -> float:
    """Search providers at *page* and append downloaded clips; returns updated duration."""
    for i, provider in enumerate(providers):
        if collected_duration >= audio_duration:
            break
        pname = _provider_name(provider)
        try:
            clips = provider.search(keywords, min_duration=2.0, page=page)
        except Exception:
            _log.warning("Scene %d: %s search raised an exception, skipping", scene_index, pname)
            continue

        if not clips:
            remaining = providers[i + 1:]
            if remaining:
                next_name = _provider_name(remaining[0])
                _log.info("Scene %d: %s returned 0 results, trying %s...", scene_index, pname, next_name)
            else:
                _log.info("Scene %d: %s returned 0 results", scene_index, pname)
            continue

        _log.info("Scene %d: %s found %d results", scene_index, pname, len(clips))
        before = len(collected)
        for clip in clips:
            if collected_duration >= audio_duration:
                break
            dest = str(scene_dir / f"scene_{scene_index:03d}_clip_{len(collected):03d}.mp4")
            try:
                download_clip(clip.url, dest)
                actual_dur = ffmpeg.get_duration(dest)
            except Exception:
                continue
            collected.append(dest)
            clip_sources[dest] = pname
            collected_duration += actual_dur
        downloaded = len(collected) - before
        _log.info("Scene %d: got %d clips from %s", scene_index, downloaded, pname)
    return collected_duration


def _loop_clips(
    collected: list[str],
    collected_duration: float,
    audio_duration: float,
    ffmpeg: FFmpegWrapper,
) -> float:
    """Repeat clips in order until collected_duration >= audio_duration; returns updated duration."""
    loop_source = list(collected)
    loop_idx = 0
    while collected_duration < audio_duration and loop_idx < 1000:
        src_path = loop_source[loop_idx % len(loop_source)]
        try:
            actual_dur = ffmpeg.get_duration(src_path)
        except Exception:
            break
        collected.append(src_path)
        collected_duration += actual_dur
        loop_idx += 1
    return collected_duration


def assemble_footage_for_scene(
    scene: Scene,
    providers: list[FootageProvider],
    ffmpeg: FFmpegWrapper,
    project_folder: Path,
    event_queue: queue.Queue,
    shortage_strategy: str = "loop",
) -> None:
    """Search providers, accumulate clips to cover audio duration, trim, mux.

    Sets scene.video_path, scene.video_duration.
    Makes ONE API call per provider (all keywords joined). If short:
      - 'loop'  → repeat existing clips until duration is met, then trim.
      - 'fetch' → make one more call per provider at page=2, then loop if still short.
    Only if no clips are found at all: marks scene.footage_shortage and skips.
    """
    audio_duration = scene.audio_duration
    scene_dir = project_folder / "video"
    collected: list[str] = []
    collected_duration = 0.0
    clip_sources: dict[str, str] = {}

    event_queue.put(ProgressEvent(
        stage="Footage Assembly",
        scene_index=scene.index,
        message=f"Searching footage for scene {scene.index}: {scene.title}",
    ))

    keywords = list(scene.visual_keywords or [scene.title])

    provider_chain = " → ".join(_provider_name(p) for p in providers)
    _log.info("Scene %d: trying providers: %s", scene.index, provider_chain)

    # Initial search: one call per provider with all keywords
    collected_duration = _collect_from_providers(
        providers, keywords, page=1,
        collected=collected, collected_duration=collected_duration,
        audio_duration=audio_duration, scene_dir=scene_dir,
        scene_index=scene.index, ffmpeg=ffmpeg, clip_sources=clip_sources,
    )

    if not collected:
        scene.footage_shortage = True
        print(f"WARNING: Scene {scene.index} skipped — no footage found, excluding from timeline")
        event_queue.put(LogEvent(
            message=f"Scene {scene.index} skipped — no footage found, excluding from timeline",
            level=LogLevel.WARNING,
        ))
        return

    # Shortage handling
    if collected_duration < audio_duration:
        if shortage_strategy == "fetch":
            collected_duration = _collect_from_providers(
                providers, keywords, page=2,
                collected=collected, collected_duration=collected_duration,
                audio_duration=audio_duration, scene_dir=scene_dir,
                scene_index=scene.index, ffmpeg=ffmpeg, clip_sources=clip_sources,
            )

        # Loop as final fallback (covers both strategies when still short)
        if collected_duration < audio_duration:
            _log.info(
                "Scene %d: looping clips to fill duration (have %.1fs, need %.1fs)",
                scene.index, collected_duration, audio_duration,
            )
            collected_duration = _loop_clips(collected, collected_duration, audio_duration, ffmpeg)

    # Log which provider(s) the clips actually used in this scene came from.
    sources_used = list(dict.fromkeys(clip_sources.get(p, "unknown") for p in collected))
    sources_note = ", ".join(sources_used) if sources_used else "unknown"
    _log.info("Scene %d: video source(s): %s", scene.index, sources_note)
    event_queue.put(LogEvent(
        message=f"Scene {scene.index}: video source(s): {sources_note}",
        level=LogLevel.INFO,
    ))

    # Concat all collected clips, then trim to exact audio duration
    raw_video = str(scene_dir / f"scene_{scene.index:03d}_raw.mp4")
    if len(collected) == 1:
        raw_video = collected[0]
    else:
        ffmpeg.concat_clips(collected, raw_video)

    trimmed_video = str(scene_dir / f"scene_{scene.index:03d}_trimmed.mp4")
    trim_duration = min(audio_duration, collected_duration)
    ffmpeg.trim_clip(raw_video, 0.0, trim_duration, trimmed_video)

    # Detect (and log) whether the source clip carries its own audio — mux_audio_video
    # always discards it and uses only the TTS track, but this makes that visible.
    try:
        had_audio = ffmpeg.has_audio_stream(trimmed_video)
    except Exception:
        had_audio = False
    audio_note = "yes" if had_audio else "no"
    _log.info(
        "Scene %d: source clip had audio: %s | audio track used: TTS",
        scene.index, audio_note,
    )
    event_queue.put(LogEvent(
        message=f"Scene {scene.index}: source clip had audio: {audio_note} | audio track used: TTS",
        level=LogLevel.INFO,
    ))

    # Mux audio + video
    muxed_video = str(scene_dir / f"scene_{scene.index:03d}_final.mp4")
    ffmpeg.mux_audio_video(trimmed_video, scene.audio_path, muxed_video)  # type: ignore[arg-type]

    scene.video_path = muxed_video
    scene.video_duration = ffmpeg.get_duration(muxed_video)

    event_queue.put(LogEvent(
        message=f"Scene {scene.index} video assembled: {scene.video_duration:.2f}s",
        level=LogLevel.INFO,
    ))


def run(
    scenes: list[Scene],
    providers: list[FootageProvider],
    ffmpeg: FFmpegWrapper,
    project_folder: Path,
    event_queue: queue.Queue,
    shortage_strategy: str = "loop",
) -> None:
    total = len(scenes)
    for scene in scenes:
        event_queue.put(ProgressEvent(
            stage="Footage Assembly",
            scene_index=scene.index,
            scene_total=total,
        ))
        assemble_footage_for_scene(
            scene, providers, ffmpeg, project_folder, event_queue, shortage_strategy,
        )

    assembled = [s for s in scenes if not s.footage_shortage]
    if not assembled:
        raise RuntimeError("No footage found for any scene — cannot build timeline.")
    scenes[:] = assembled
