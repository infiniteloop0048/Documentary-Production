"""FFmpeg operations specific to Shorts/Reels assembly.

Subclasses FFmpegWrapper to reuse its ffmpeg/ffprobe binary resolution and the
_check() error-raising helper — the base class is never edited, only extended.
"""
from __future__ import annotations

import logging
import re
import subprocess

from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_log = logging.getLogger(__name__)

_MOTION_SAMPLE_WIDTH = 160
_MOTION_DETECT_TIMEOUT = 10.0
# 40% into the clip — inside the spec's required 20-60% fallback band.
_FALLBACK_WINDOW_FRACTION = 0.4

SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920


class ShortsFFmpeg(FFmpegWrapper):
    """FFmpeg operations used only by the Shorts/Reels assembly path."""

    def detect_motion_window(
        self, clip_path: str, clip_duration: float, window: float
    ) -> tuple[float, str]:
        """Return (start_time, method) for the *window*-second slice of *clip_path*
        with the highest motion, sampled at low resolution via scene-change scores.

        Falls back to a window starting 40% into the clip (within the spec's 20-60%
        band) on any ffmpeg error or if analysis exceeds _MOTION_DETECT_TIMEOUT seconds.
        """
        usable = max(0.0, clip_duration - window)
        if usable <= 0:
            return 0.0, "fallback"
        try:
            cmd = [
                self._ffmpeg, "-y",
                "-i", clip_path,
                "-vf", (
                    f"scale={_MOTION_SAMPLE_WIDTH}:-1,"
                    "select='gt(scene\\,0.1)',metadata=print"
                ),
                "-an", "-f", "null", "-",
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_MOTION_DETECT_TIMEOUT,
            )
            self._check(result, f"detect_motion_window → {clip_path!r}")
            best_time, used_fallback = self._best_scene_time(result.stderr, usable, clip_duration)
            return best_time, "fallback" if used_fallback else "motion"
        except Exception as exc:
            _log.info("detect_motion_window: falling back for %s (%s)", clip_path, exc)
            return min(round(clip_duration * _FALLBACK_WINDOW_FRACTION, 2), usable), "fallback"

    @staticmethod
    def _best_scene_time(
        ffmpeg_stderr: str, usable: float, clip_duration: float
    ) -> tuple[float, bool]:
        """Parse 'pts_time:X' markers from ffmpeg's scene-metadata stderr and return
        (time, used_fallback) — the latest marker that still leaves room for a full
        window, or the fallback point (with used_fallback=True) if none were found."""
        times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", ffmpeg_stderr)]
        candidates = [t for t in times if t <= usable]
        if not candidates:
            fallback = min(round(clip_duration * _FALLBACK_WINDOW_FRACTION, 2), usable)
            return fallback, True
        return round(max(candidates), 2), False

    def vertical_convert(self, input_path: str, output_path: str, strategy: str) -> None:
        """Convert *input_path* to a 1080x1920 vertical video.

        strategy='center_crop': scale to fill the target frame, crop the excess width.
        strategy='blur_pad': blurred scaled-fill copy behind an aspect-fit foreground.
        """
        if strategy == "blur_pad":
            filter_complex = (
                f"[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={SHORTS_WIDTH}:{SHORTS_HEIGHT},gblur=sigma=20[bg];"
                f"[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
            )
        else:
            filter_complex = (
                f"[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={SHORTS_WIDTH}:{SHORTS_HEIGHT}[vout]"
            )
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"vertical_convert({strategy}) → {output_path!r}")

    def apply_ken_burns(
        self, input_path: str, output_path: str, duration: float, direction: str, pan: bool
    ) -> None:
        """Apply a slow zoompan (Ken Burns) effect over the exact *duration* of the clip.

        direction='in' zooms 1.0→1.08, direction='out' zooms 1.08→1.0. When *pan* is
        True, a slight horizontal pan is layered on top of the zoom. The transform
        completes over exactly *duration* seconds (d=frames at the target fps).
        """
        fps = 30
        frames = max(1, round(duration * fps))
        if direction == "in":
            zoom_expr = "min(zoom+0.0015,1.08)"
        else:
            zoom_expr = "if(eq(on,0),1.08,max(zoom-0.0015,1.0))"
        if pan:
            x_expr = f"iw/2-(iw/zoom/2)+(on/{frames})*40"
        else:
            x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
        zoompan = (
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={SHORTS_WIDTH}x{SHORTS_HEIGHT}:fps={fps}"
        )
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-vf", zoompan,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_ken_burns({direction}) → {output_path!r}")

    def concat_segments_video_only(self, input_paths: list[str], output_path: str) -> None:
        """Concatenate already-vertical, already-Ken-Burns'd segment videos (video only)."""
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

    def mux_shorts_audio(self, video_path: str, audio_path: str, output_path: str) -> None:
        """Mux the concatenated vertical video with the TTS audio track.

        Explicit -map discipline identical to FFmpegWrapper.mux_audio_video: video
        from *video_path* only, audio from *audio_path* only — never let ffmpeg
        auto-pick an audio stream from source footage.
        """
        result = subprocess.run(
            [
                self._ffmpeg, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                output_path,
            ],
            capture_output=True,
            text=True,
        )
        self._check(result, f"mux_shorts_audio → {output_path!r}")
