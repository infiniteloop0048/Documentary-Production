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

    def concat_segments(
        self, input_paths: list[str], output_resolution: str, output_path: str
    ) -> None:
        """Concatenate already-normalized Clip Story segments into the final
        output, scaling to the project's chosen canvas. Segments are already
        uniform resolution/SAR/pixfmt (normalize_clip already ran on each), so
        this only needs to guarantee a consistent fps before concatenation —
        unlike the shared concat_scenes (media/ffmpeg_wrapper.py), which
        hardcodes 1920x1080 for the always-16:9 Documentary pipeline."""
        if output_resolution not in _OUTPUT_RESOLUTIONS:
            raise ValueError(f"Unknown output_resolution: {output_resolution!r}")
        w, h = _OUTPUT_RESOLUTIONS[output_resolution]
        n = len(input_paths)
        scale_parts = ";".join(f"[{i}:v]fps=30,scale={w}:{h}[v{i}]" for i in range(n))
        interleaved = "".join(f"[v{i}][{i}:a]" for i in range(n))
        filter_complex = scale_parts + f";{interleaved}concat=n={n}:v=1:a=1[outv][outa]"
        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_segments → {output_path!r}")
