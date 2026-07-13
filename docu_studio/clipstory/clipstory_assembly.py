"""Per-clip Clip Story render pipeline: trim -> measure real duration -> normalize
-> TTS -> Layer 2/3 fit -> reconciliation -> mux -> (all clips) hard-cut concat.
See docs/superpowers/specs/2026-07-13-clipstory-phase1-design.md for the full
per-clip pipeline and the rationale for measuring the trimmed file's real
duration rather than trusting trim_out - trim_in arithmetic.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from threading import Event

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.clipstory.clipstory_config import ClipStoryConfig
from docu_studio.clipstory.clipstory_ffmpeg import _OUTPUT_RESOLUTIONS, ClipStoryFFmpeg
from docu_studio.clipstory.clipstory_pacing import evaluate_fit, plan_reconciliation

_log = logging.getLogger(__name__)

_TRANSITION_DURATION = 0.5


class ClipStoryFitError(Exception):
    """Raised when Layer 3 halts the render — the exception message carries the
    full per-clip numeric report (target/actual/factors/residual) for every clip
    processed so far, so the GUI's existing error-display surfaces real numbers."""


class ClipStoryTransitionError(Exception):
    """Raised when a crossfade transition is requested but at least one clip's
    measured duration is too short to support the fixed transition length —
    the xfade offset= math would go negative/invalid for that pair. Halt
    rather than silently clamp or produce broken ffmpeg output, same
    halt-and-report philosophy as ClipStoryFitError."""


def assemble_clip_story(
    config: ClipStoryConfig,
    tts: TTSProvider,
    work_dir: Path,
    output_path: Path,
    cancel_event: Event | None = None,
    music_path: str | None = None,
) -> None:
    ffmpeg = ClipStoryFFmpeg()
    segment_paths: list[str] = []
    segment_durations: list[float] = []
    report_lines: list[str] = []

    for i, clip in enumerate(config.clips):
        if cancel_event is not None and cancel_event.is_set():
            return

        trimmed_path = str(work_dir / f"clip_{i}_trimmed.mp4")
        ffmpeg.trim_clip(clip.path, clip.trim_in, clip.trim_out - clip.trim_in, trimmed_path)
        # Measured, not trim_out - trim_in arithmetic: ffmpeg trims aren't always
        # frame-exact, and this value is authoritative for everything below.
        measured_target_duration = ffmpeg.get_duration(trimmed_path)
        segment_durations.append(measured_target_duration)

        normalized_path = str(work_dir / f"clip_{i}_normalized.mp4")
        ffmpeg.normalize_clip(trimmed_path, config.output_resolution, normalized_path)
        video_for_mux_path = normalized_path

        raw_narration_path = str(work_dir / f"clip_{i}_narration_raw.mp3")
        actual_duration = tts.synthesize(clip.script_text, raw_narration_path)

        fit = evaluate_fit(actual_duration, measured_target_duration)
        report_line = (
            f"Clip {i} ({Path(clip.path).name}): target={measured_target_duration:.2f}s "
            f"actual={actual_duration:.2f}s ideal_factor={fit.ideal_factor:.3f} "
            f"applied_factor={fit.applied_factor:.3f} resulting={fit.resulting_duration:.2f}s "
            f"residual={fit.residual_ratio * 100:.1f}%"
        )
        report_lines.append(report_line)
        _log.info(report_line)
        if fit.should_halt:
            raise ClipStoryFitError(
                "Clip Story render halted: narration pacing gap too large to fix "
                "automatically.\n" + "\n".join(report_lines)
            )

        tempo_path = str(work_dir / f"clip_{i}_narration_tempo.mp3")
        ffmpeg.apply_atempo(raw_narration_path, fit.applied_factor, tempo_path)

        post_tempo_duration = ffmpeg.get_duration(tempo_path)
        plan = plan_reconciliation(post_tempo_duration, measured_target_duration)
        final_narration_path = str(work_dir / f"clip_{i}_narration_final.mp3")
        ffmpeg.apply_reconciliation(
            tempo_path, plan, measured_target_duration, final_narration_path
        )
        _log.info(
            "Clip %d reconciliation: action=%s adjustment=%.3fs",
            i, plan.action, plan.adjustment_seconds,
        )

        if config.captions:
            from docu_studio.common.captions import estimate_word_timestamps, write_ass_file

            timings = estimate_word_timestamps(clip.script_text, measured_target_duration)
            ass_path = str(work_dir / f"clip_{i}_captions.ass")
            out_w, out_h = _OUTPUT_RESOLUTIONS[config.output_resolution]
            write_ass_file(timings, ass_path, out_w, out_h, measured_target_duration)
            captioned_path = str(work_dir / f"clip_{i}_captioned.mp4")
            ffmpeg.burn_captions(normalized_path, ass_path, captioned_path)
            video_for_mux_path = captioned_path

        segment_path = str(work_dir / f"clip_{i}_segment.mp4")
        ffmpeg.mux_audio_video(video_for_mux_path, final_narration_path, segment_path)
        segment_paths.append(segment_path)

    if cancel_event is not None and cancel_event.is_set():
        return

    # Segments are already uniform resolution/SAR/pixfmt (normalize_clip) and
    # already have narration muxed in — concat_segments just hard-cuts them
    # together, scaled to the project's chosen canvas (16:9 or 9:16).
    assembled_path = str(work_dir / "clipstory_assembled.mp4")
    if config.transition == "crossfade" and len(segment_paths) > 1:
        too_short = [
            (i, d) for i, d in enumerate(segment_durations) if d <= _TRANSITION_DURATION
        ]
        if too_short:
            details = ", ".join(f"clip {i} ({d:.2f}s)" for i, d in too_short)
            raise ClipStoryTransitionError(
                f"Clip Story crossfade requires every clip to be longer than "
                f"{_TRANSITION_DURATION}s; too short: {details}"
            )
        ffmpeg.concat_segments_with_xfade(
            segment_paths, segment_durations, _TRANSITION_DURATION, assembled_path,
        )
    else:
        ffmpeg.concat_segments(segment_paths, config.output_resolution, assembled_path)

    if music_path:
        total_duration = ffmpeg.get_duration(assembled_path)
        mixed_audio_path = str(work_dir / "clipstory_music_mixed.m4a")
        ffmpeg.mix_music_bed(assembled_path, music_path, total_duration, mixed_audio_path)
        ffmpeg.mux_audio_video(assembled_path, mixed_audio_path, str(output_path))
    else:
        shutil.copy(assembled_path, str(output_path))
