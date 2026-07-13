"""Per-clip Clip Story render pipeline: trim -> measure real duration -> normalize
-> TTS -> Layer 2/3 fit -> reconciliation -> mux -> (all clips) hard-cut concat.
See docs/superpowers/specs/2026-07-13-clipstory-phase1-design.md for the full
per-clip pipeline and the rationale for measuring the trimmed file's real
duration rather than trusting trim_out - trim_in arithmetic.
"""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.clipstory.clipstory_config import ClipStoryConfig
from docu_studio.clipstory.clipstory_ffmpeg import ClipStoryFFmpeg
from docu_studio.clipstory.clipstory_pacing import evaluate_fit, plan_reconciliation

_log = logging.getLogger(__name__)


class ClipStoryFitError(Exception):
    """Raised when Layer 3 halts the render — the exception message carries the
    full per-clip numeric report (target/actual/factors/residual) for every clip
    processed so far, so the GUI's existing error-display surfaces real numbers."""


def assemble_clip_story(
    config: ClipStoryConfig,
    tts: TTSProvider,
    work_dir: Path,
    output_path: Path,
    cancel_event: Event | None = None,
) -> None:
    ffmpeg = ClipStoryFFmpeg()
    segment_paths: list[str] = []
    report_lines: list[str] = []

    for i, clip in enumerate(config.clips):
        if cancel_event is not None and cancel_event.is_set():
            return

        trimmed_path = str(work_dir / f"clip_{i}_trimmed.mp4")
        ffmpeg.trim_clip(clip.path, clip.trim_in, clip.trim_out - clip.trim_in, trimmed_path)
        # Measured, not trim_out - trim_in arithmetic: ffmpeg trims aren't always
        # frame-exact, and this value is authoritative for everything below.
        measured_target_duration = ffmpeg.get_duration(trimmed_path)

        normalized_path = str(work_dir / f"clip_{i}_normalized.mp4")
        ffmpeg.normalize_clip(trimmed_path, config.output_resolution, normalized_path)

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

        segment_path = str(work_dir / f"clip_{i}_segment.mp4")
        ffmpeg.mux_audio_video(normalized_path, final_narration_path, segment_path)
        segment_paths.append(segment_path)

    if cancel_event is not None and cancel_event.is_set():
        return

    # Segments are already uniform resolution/SAR/pixfmt (normalize_clip) and
    # already have narration muxed in — concat_segments just hard-cuts them
    # together, scaled to the project's chosen canvas (16:9 or 9:16).
    ffmpeg.concat_segments(segment_paths, config.output_resolution, str(output_path))
