"""FFmpeg operations specific to Shorts/Reels assembly.

Subclasses FFmpegWrapper to reuse its ffmpeg/ffprobe binary resolution and the
_check() error-raising helper — the base class is never edited, only extended.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess

from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_log = logging.getLogger(__name__)

_MOTION_SAMPLE_WIDTH = 160
# Analysis only needs to see the first slice of the source — most stock clips
# have their best motion well inside this, and capping it keeps long/high-fps
# sources from blowing the analysis budget.
_MOTION_ANALYSIS_MAX_DURATION = 30.0
_MOTION_ANALYSIS_FPS = 5
_MOTION_DETECT_TIMEOUT = 20.0
# 40% into the clip — inside the spec's required 20-60% fallback band.
_FALLBACK_WINDOW_FRACTION = 0.4

SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920

_PUNCH_CARD_BG = "0x141620"
# Scale-in completes over the first quarter of the card's own length.
_PUNCH_SCALE_IN_FRACTION = 0.25


class ShortsFFmpeg(FFmpegWrapper):
    """FFmpeg operations used only by the Shorts/Reels assembly path."""

    def detect_motion_window(
        self, clip_path: str, clip_duration: float, window: float
    ) -> tuple[float, str]:
        """Return (start_time, method) for the *window*-second slice of *clip_path*
        with the highest motion, sampled at low resolution via scene-change scores.

        Analysis is capped to the first _MOTION_ANALYSIS_MAX_DURATION seconds of the
        source (via -t before -i) and to _MOTION_ANALYSIS_FPS, on top of the 160px
        downscale, so typical 15-60s stock clips finish comfortably inside the
        timeout instead of exhausting it. Falls back to a window starting 40% into
        the clip (within the spec's 20-60% band) on any ffmpeg error or if analysis
        still exceeds _MOTION_DETECT_TIMEOUT seconds.
        """
        usable = max(0.0, clip_duration - window)
        if usable <= 0:
            return 0.0, "fallback"
        try:
            cmd = [
                self._ffmpeg, "-y",
                "-t", str(_MOTION_ANALYSIS_MAX_DURATION),
                "-i", clip_path,
                "-vf", (
                    f"fps={_MOTION_ANALYSIS_FPS},scale={_MOTION_SAMPLE_WIDTH}:-1,"
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

        zoompan crops on integer pixel coordinates at whatever resolution it's fed,
        so at native 1080x1920 each 1.0015x zoom increment can round to the same
        source pixel for several output frames in a row — visible stepping. Scaling
        up 4x first (lanczos) before zoompan makes every increment land on a distinct
        source pixel, and using a zoom expression that's a pure function of the
        output frame number ('on') instead of the classic 'zoom+0.001' accumulator
        avoids the drift/stutter that pattern causes over a long segment.
        """
        fps = 30
        frames = max(1, round(duration * fps))
        denom = max(frames - 1, 1)
        target_zoom = 1.08
        zoom_delta = target_zoom - 1.0
        if direction == "in":
            zoom_expr = f"1+{zoom_delta}*on/{denom}"
        else:
            zoom_expr = f"{target_zoom}-{zoom_delta}*on/{denom}"
        if pan:
            x_expr = f"iw/2-(iw/zoom/2)+(on/{denom})*40"
        else:
            x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
        upscale_dim = SHORTS_WIDTH * 4
        vf = (
            f"scale={upscale_dim}:-2:flags=lanczos,"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={SHORTS_WIDTH}x{SHORTS_HEIGHT}:fps={fps}"
        )
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_ken_burns({direction}) → {output_path!r}")

    def apply_speed_ramp(self, input_path: str, output_path: str, speed_factor: float) -> None:
        """Speed up *input_path*'s video stream by *speed_factor* via setpts
        (video only — the caller always re-attaches the TTS audio track
        separately, so no audio stream is read or written here)."""
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-vf", f"setpts=PTS/{speed_factor}",
            "-an",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_speed_ramp(factor={speed_factor}) → {output_path!r}")

    def generate_punch_card(self, output_path: str, text: str, duration: float) -> None:
        """Render a *duration*-second full-frame punch card: theme-dark
        background, huge bold centered white text, with a quick zoompan
        scale-in over the first _PUNCH_SCALE_IN_FRACTION of its length —
        reusing apply_ken_burns' frame-linear zoompan recipe so the scale
        lands exactly on the card's own frame count."""
        escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        fps = 30
        frames = max(1, round(duration * fps))
        scale_frames = max(1, round(frames * _PUNCH_SCALE_IN_FRACTION))
        zoom_expr = f"if(lte(on\\,{scale_frames})\\,0.85+0.15*on/{scale_frames}\\,1.0)"

        base_path = f"{output_path}.base.mp4"
        base_cmd = [
            self._ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c={_PUNCH_CARD_BG}:s={SHORTS_WIDTH}x{SHORTS_HEIGHT}:d={duration}:r={fps}",
            "-vf", (
                f"drawtext=text='{escaped}':fontcolor=white:fontsize=120:"
                "x=(w-text_w)/2:y=(h-text_h)/2:font=DejaVu Sans Bold"
            ),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            base_path,
        ]
        result = subprocess.run(base_cmd, capture_output=True, text=True)
        self._check(result, f"generate_punch_card(base) → {base_path!r}")

        upscale_dim = SHORTS_WIDTH * 4
        vf = (
            f"scale={upscale_dim}:-2:flags=lanczos,"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={SHORTS_WIDTH}x{SHORTS_HEIGHT}:fps={fps}"
        )
        cmd = [
            self._ffmpeg, "-y",
            "-i", base_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"generate_punch_card(scale-in) → {output_path!r}")

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

    def burn_captions(self, input_path: str, ass_path: str, output_path: str) -> None:
        """Burn *ass_path* (ASS pop-caption subtitles) into *input_path* via
        ffmpeg's subtitles filter. *input_path* here is the video-only concat
        output — no audio stream to preserve at this stage.

        ffmpeg's -vf value is parsed by the avfilter graph description parser,
        which splits on unescaped ':' — this breaks on any colon in the path
        (guaranteed on Windows drive letters like "C:\\...", and no universal
        escaping of the colon reliably survives both that parser AND avio's
        own protocol-scheme detection, which independently misreads a bare
        "C:" prefix as a "C" protocol). Sidestepping both entirely: run ffmpeg
        with cwd set to the subtitle file's own directory and reference only
        its bare filename (never containing a colon) in the filter string.
        input_path/output_path are unaffected — they're plain argv values,
        not filtergraph-string content, so they still take absolute paths.
        """
        ass_dir = os.path.dirname(ass_path) or "."
        ass_name = os.path.basename(ass_path)
        cmd = [
            self._ffmpeg, "-y",
            "-i", os.path.abspath(input_path),
            "-vf", f"subtitles={ass_name}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            os.path.abspath(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=ass_dir)
        self._check(result, f"burn_captions → {output_path!r}")

    def mix_music_bed(
        self, voice_path: str, music_path: str, video_duration: float, output_path: str
    ) -> None:
        """Loop/trim *music_path* to *video_duration*, duck it under
        *voice_path* via sidechaincompress, and write the mixed result to
        *output_path* as a standalone audio file — the caller (assemble_short)
        passes this into mux_shorts_audio exactly as it would the raw voice
        track, so that method's -map discipline never needs to change."""
        from docu_studio.shorts.shorts_audio_mix import build_ducking_filtergraph

        filter_complex = build_ducking_filtergraph(video_duration)
        cmd = [
            self._ffmpeg, "-y",
            "-i", voice_path,
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "aac",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"mix_music_bed → {output_path!r}")

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
