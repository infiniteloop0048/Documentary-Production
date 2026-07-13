"""ClipStoryFFmpeg: adds atempo pacing, per-clip resolution normalization, audio
reconciliation (pad/trim-fade), and poster-frame extraction on top of the shared
FFmpegWrapper. Every clip is normalized before mux/concat because uploaded videos
arrive in far more heterogeneous encodings than Shorts/Slideshow's stock footage —
see docs/superpowers/specs/2026-07-13-clipstory-phase1-design.md.
"""
from __future__ import annotations

import shutil
import subprocess

from docu_studio.clipstory.clipstory_pacing import ReconciliationPlan
from docu_studio.common.ffmpeg_finalize import finalize_filter
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_OUTPUT_RESOLUTIONS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}


class ClipStoryFFmpeg(FFmpegWrapper):
    def normalize_clip(self, input_path: str, output_resolution: str, output_path: str) -> None:
        if output_resolution not in _OUTPUT_RESOLUTIONS:
            raise ValueError(f"Unknown output_resolution: {output_resolution!r}")
        w, h = _OUTPUT_RESOLUTIONS[output_resolution]
        vf = finalize_filter(
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        result = subprocess.run(
            [self._ffmpeg, "-y", "-i", input_path, "-vf", vf,
             "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-an", output_path],
            capture_output=True, text=True,
        )
        self._check(result, f"normalize_clip → {output_path!r}")

    def apply_atempo(self, input_path: str, speed_factor: float, output_path: str) -> None:
        result = subprocess.run(
            [self._ffmpeg, "-y", "-i", input_path,
             "-filter:a", f"atempo={speed_factor}", "-vn", output_path],
            capture_output=True, text=True,
        )
        self._check(result, f"apply_atempo → {output_path!r}")

    def apply_reconciliation(
        self,
        input_path: str,
        plan: ReconciliationPlan,
        target_duration: float,
        output_path: str,
        fade_duration: float = 0.3,
    ) -> None:
        if plan.action == "pad":
            af = f"apad=pad_dur={plan.adjustment_seconds}"
            result = subprocess.run(
                [self._ffmpeg, "-y", "-i", input_path, "-af", af, output_path],
                capture_output=True, text=True,
            )
            self._check(result, f"apply_reconciliation(pad) → {output_path!r}")
        elif plan.action == "trim_fade":
            fade_start = max(0.0, target_duration - fade_duration)
            af = f"atrim=0:{target_duration},afade=t=out:st={fade_start}:d={fade_duration}"
            result = subprocess.run(
                [self._ffmpeg, "-y", "-i", input_path, "-af", af, output_path],
                capture_output=True, text=True,
            )
            self._check(result, f"apply_reconciliation(trim_fade) → {output_path!r}")
        else:
            shutil.copy(input_path, output_path)

    def extract_poster_frame(self, video_path: str, timestamp: float, output_path: str) -> None:
        result = subprocess.run(
            [self._ffmpeg, "-y", "-ss", str(timestamp), "-i", video_path,
             "-frames:v", "1", "-q:v", "3", output_path],
            capture_output=True, text=True,
        )
        self._check(result, f"extract_poster_frame → {output_path!r}")
