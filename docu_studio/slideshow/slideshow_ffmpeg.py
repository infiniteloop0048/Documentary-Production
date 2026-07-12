"""FFmpeg operations specific to Slideshow assembly.

Subclasses FFmpegWrapper to reuse its ffmpeg/ffprobe binary resolution, the
_check() error-raising helper, get_duration(), and mux_audio_video() — the
base class is never edited, only extended, same discipline as ShortsFFmpeg.

apply_ken_burns_image reuses the Ken Burns fix verbatim from
docu_studio/shorts/shorts_ffmpeg.py (4x lanczos upscale before zoompan,
non-accumulating zoom expression, setsar=1/format=yuv420p finalize) but
generalizes it two ways Shorts doesn't need: output width/height are
parameters (Shorts hardcodes 1080x1920), and the crop-to-target-aspect step
is folded into the same filter chain (Shorts does that separately in
vertical_convert before Ken Burns ever runs on video; a still image has no
separate pre-crop pass).
"""
from __future__ import annotations

import subprocess

from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

# Same rationale as shorts_ffmpeg.py's _SAR_PIXFMT_SUFFIX: chained scale
# operations can round the encoded SAR to a near-1:1-but-not-exact value,
# and ffmpeg's concat filter rejects segments whose SAR doesn't match
# exactly. Every per-segment filter chain must end with this suffix.
_SAR_PIXFMT_SUFFIX = "setsar=1,format=yuv420p"


class SlideshowFFmpeg(FFmpegWrapper):
    """FFmpeg operations used only by the Slideshow assembly path."""

    @staticmethod
    def _finalize_filter(filter_chain: str) -> str:
        return f"{filter_chain},{_SAR_PIXFMT_SUFFIX}"

    @staticmethod
    def _xfade_offsets(durations: list[float], transition_duration: float) -> list[float]:
        """Return the N-1 ffmpeg `offset=` values for chaining `xfade` across
        N segments of the given *durations* (already inflated by the caller
        so the post-crossfade total equals the pre-inflation sum — see
        slideshow_assembly.crossfade_segment_durations). Each offset is the
        point in the running merged timeline where the next segment's
        crossfade begins: cumulative_duration_so_far - transition_duration."""
        offsets: list[float] = []
        cumulative = durations[0]
        for d in durations[1:]:
            offset = cumulative - transition_duration
            offsets.append(offset)
            cumulative = offset + d
        return offsets

    def concat_segments_with_xfade(
        self, input_paths: list[str], durations: list[float],
        transition_duration: float, output_path: str,
    ) -> None:
        """Concatenate already-Ken-Burns'd segment videos with a crossfade
        (ffmpeg's xfade filter) between each pair, instead of a hard cut.
        *durations* are the segments' actual rendered lengths (inflated by
        transition_duration on all but the last, per
        slideshow_assembly.crossfade_segment_durations), used here to compute
        each xfade's `offset=`. The final xfade stage is finalized through
        the same setsar=1,format=yuv420p suffix apply_ken_burns_image uses,
        so this new concat path can't reintroduce the SAR concat-crash bug."""
        n = len(input_paths)
        if n < 2:
            raise ValueError("concat_segments_with_xfade requires at least 2 segments")
        offsets = self._xfade_offsets(durations, transition_duration)

        stages = []
        prev_label = "[0:v]"
        for i in range(1, n):
            next_label = f"[{i}:v]"
            is_last = i == n - 1
            out_label = "[vout]" if is_last else f"[x{i}]"
            stage = (
                f"{prev_label}{next_label}xfade=transition=fade:"
                f"duration={transition_duration:.2f}:offset={offsets[i - 1]:.3f}"
            )
            if is_last:
                stage += f",{_SAR_PIXFMT_SUFFIX}"
            stage += out_label
            stages.append(stage)
            prev_label = f"[x{i}]"
        filter_complex = ";".join(stages)

        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_segments_with_xfade → {output_path!r}")

    def apply_ken_burns_image(
        self, input_path: str, output_path: str, duration: float,
        direction: str, out_width: int, out_height: int,
    ) -> None:
        """Render *duration* seconds of Ken Burns motion over a still image
        at *out_width*x*out_height*.

        direction='in' zooms 1.0->1.08, direction='out' zooms 1.08->1.0.
        -loop 1 is required because a still image is a single-frame input —
        without it ffmpeg has nothing left to feed zoompan after frame one.
        """
        fps = 30
        frames = max(1, round(duration * fps))
        denom = max(frames - 1, 1)
        target_zoom = 1.08
        zoom_delta = target_zoom - 1.0
        if direction == "in":
            zoom_expr = f"1+{zoom_delta:.2f}*on/{denom}"
        else:
            zoom_expr = f"{target_zoom}-{zoom_delta:.2f}*on/{denom}"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
        upscale_dim = out_width * 4
        vf = self._finalize_filter(
            f"scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
            f"crop={out_width}:{out_height},"
            f"scale={upscale_dim}:-2:flags=lanczos,"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={out_width}x{out_height}:fps={fps}"
        )
        cmd = [
            self._ffmpeg, "-y",
            "-loop", "1",
            "-i", input_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_ken_burns_image({direction}) → {output_path!r}")

    def concat_segments_video_only(self, input_paths: list[str], output_path: str) -> None:
        """Concatenate already-Ken-Burns'd segment videos (video only, hard
        cut). Same filter_complex-concat technique as
        ShortsFFmpeg.concat_segments_video_only — copied rather than
        imported to keep this package's only dependency on shorts/ at zero,
        per the Phase 1 design decision to defer all shared-code extraction."""
        n = len(input_paths)
        concat_inputs = "".join(f"[{i}:v]" for i in range(n))
        filter_complex = f"{concat_inputs}concat=n={n}:v=1:a=0[vout]"
        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_segments_video_only → {output_path!r}")
