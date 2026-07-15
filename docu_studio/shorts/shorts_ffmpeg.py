"""FFmpeg operations specific to Shorts/Reels assembly.

Subclasses FFmpegWrapper to reuse its ffmpeg/ffprobe binary resolution and the
_check() error-raising helper — the base class is never edited, only extended.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from docu_studio.common.ffmpeg_finalize import finalize_filter
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper
from docu_studio.shorts.shorts_config import SHORTS_HEIGHT, SHORTS_WIDTH

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

_PUNCH_CARD_BG = "0x141620"
_PUNCH_FONT_NAME = "DejaVu Sans"
_PUNCH_SCALE_IN_MS = 200  # scale-in transform completes over this many ms


class ShortsFFmpeg(FFmpegWrapper):
    """FFmpeg operations used only by the Shorts/Reels assembly path."""

    def detect_motion_window(
        self, clip_path: str, clip_duration: float, window: float
    ) -> tuple[float, str]:
        """Return (start_time, method) for the *window*-second slice of *clip_path*
        with the highest motion.

        Three-tier chain, each tier logging its own outcome/reason to shorts_log.txt:
        1. Scene-change detection (cheap, works great for clips with hard cuts) —
           method="motion" on success.
        2. Motion-energy sampling (signalstats frame-to-frame diff) — for clips with
           continuous smooth motion (slow drone shots, static-ish wide shots) that
           never cross the scene-change threshold — method="motion_energy" on success.
        3. Dumb positional fallback (40% into the clip) as the last resort —
           method="fallback".

        Analysis is capped to the first _MOTION_ANALYSIS_MAX_DURATION seconds of the
        source (via -t before -i) and to _MOTION_ANALYSIS_FPS, on top of the 160px
        downscale, so typical 15-60s stock clips finish comfortably inside the
        timeout instead of exhausting it. Falls all the way to tier 3 on any ffmpeg
        error or if analysis still exceeds _MOTION_DETECT_TIMEOUT seconds.
        """
        # Unconditional per-call marker: a long-running app process keeps whatever
        # module code was imported at startup in memory, so editing this file on
        # disk has no effect until the process restarts. This line lets any run's
        # shorts_log.txt prove which chain is actually executing instead of having
        # to infer it from log-message archaeology.
        _log.info("detect_motion_window: tier-chain=scene-change/motion-energy/fallback analyzing %s", clip_path)
        usable = max(0.0, clip_duration - window)
        if usable <= 0:
            _log.info(
                "detect_motion_window: %s — window (%.2fs) >= clip_duration (%.2fs), "
                "no usable range — fallback",
                clip_path, window, clip_duration,
            )
            return 0.0, "fallback"
        fallback_time = min(round(clip_duration * _FALLBACK_WINDOW_FRACTION, 2), usable)
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
        except subprocess.TimeoutExpired:
            _log.info(
                "detect_motion_window: %s — scene-change analysis timed out after %.1fs "
                "— trying motion-energy fallback",
                clip_path, _MOTION_DETECT_TIMEOUT,
            )
            return self._motion_energy_or_fallback(clip_path, window, usable, fallback_time)
        except Exception as exc:
            _log.info(
                "detect_motion_window: %s — scene-change analysis subprocess/ffmpeg error "
                "(%s) — trying motion-energy fallback",
                clip_path, exc,
            )
            return self._motion_energy_or_fallback(clip_path, window, usable, fallback_time)

        best_time, used_fallback, n_markers = self._best_scene_time(result.stderr, usable, clip_duration)
        if not used_fallback:
            _log.info(
                "detect_motion_window: %s — motion window found via scene-change "
                "(start=%.2f, %d markers detected)",
                clip_path, best_time, n_markers,
            )
            return best_time, "motion"

        _log.info(
            "detect_motion_window: %s — zero scene-change markers above threshold "
            "usable in range (found %d total) — trying motion-energy fallback",
            clip_path, n_markers,
        )
        return self._motion_energy_or_fallback(clip_path, window, usable, fallback_time)

    def _motion_energy_or_fallback(
        self, clip_path: str, window: float, usable: float, fallback_time: float
    ) -> tuple[float, str]:
        """Tier 2→3: try motion-energy sampling; if it finds nothing usable
        (or errors/times out), fall through to the dumb positional fallback.
        Always logs the outcome — this is the tripwire for telling "still
        timing out" apart from "legitimately zero motion signal"."""
        energy_start = self._detect_motion_energy_window(clip_path, window, usable)
        if energy_start is not None:
            _log.info(
                "detect_motion_window: %s — motion window found via motion-energy "
                "sampling (start=%.2f)",
                clip_path, energy_start,
            )
            return energy_start, "motion_energy"
        _log.info(
            "detect_motion_window: %s — motion-energy sampling also found nothing "
            "usable — dumb fallback (start=%.2f)",
            clip_path, fallback_time,
        )
        return fallback_time, "fallback"

    def _detect_motion_energy_window(
        self, clip_path: str, window: float, usable: float
    ) -> float | None:
        """Sample frame-to-frame luma difference (signalstats YDIF) across the
        clip and return the start time of the *window*-second slice with the
        highest average motion energy, or None on any error/timeout or if no
        usable samples were found. Unlike scene-change detection (a binary
        threshold looking for hard cuts), this works for clips with continuous
        smooth motion (slow pans, drone shots, calm scenery) that never
        produce a scene-change spike."""
        try:
            cmd = [
                self._ffmpeg, "-y",
                "-t", str(_MOTION_ANALYSIS_MAX_DURATION),
                "-i", clip_path,
                "-vf", (
                    f"fps={_MOTION_ANALYSIS_FPS},scale={_MOTION_SAMPLE_WIDTH}:-1,"
                    "signalstats,metadata=print:key=lavfi.signalstats.YDIF"
                ),
                "-an", "-f", "null", "-",
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_MOTION_DETECT_TIMEOUT,
            )
            self._check(result, f"_detect_motion_energy_window → {clip_path!r}")
        except subprocess.TimeoutExpired:
            _log.info(
                "detect_motion_window: %s — motion-energy analysis timed out after %.1fs",
                clip_path, _MOTION_DETECT_TIMEOUT,
            )
            return None
        except Exception as exc:
            _log.info(
                "detect_motion_window: %s — motion-energy analysis subprocess/ffmpeg "
                "error (%s)",
                clip_path, exc,
            )
            return None
        return self._best_energy_window(result.stderr, usable, window)

    @staticmethod
    def _best_scene_time(
        ffmpeg_stderr: str, usable: float, clip_duration: float
    ) -> tuple[float, bool, int]:
        """Parse 'pts_time:X' markers from ffmpeg's scene-metadata stderr and return
        (time, used_fallback, n_markers_found) — the latest marker that still leaves
        room for a full window, or the fallback point (with used_fallback=True) if
        none were found or none fit within the usable range."""
        times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", ffmpeg_stderr)]
        candidates = [t for t in times if t <= usable]
        if not candidates:
            fallback = min(round(clip_duration * _FALLBACK_WINDOW_FRACTION, 2), usable)
            return fallback, True, len(times)
        return round(max(candidates), 2), False, len(times)

    @staticmethod
    def _best_energy_window(ffmpeg_stderr: str, usable: float, window: float) -> float | None:
        """Parse (pts_time, YDIF) sample pairs from signalstats metadata=print
        stderr and return the start time of the *window*-second slice with the
        highest average motion energy, or None if no usable samples were found."""
        pairs = re.findall(
            r"pts_time:([\d.]+)[^\n]*\n[^\n]*lavfi\.signalstats\.YDIF=([\d.]+)", ffmpeg_stderr,
        )
        samples = [(float(t), float(v)) for t, v in pairs]
        candidates = sorted({t for t, _ in samples if t <= usable})
        if not candidates:
            return None
        best_start, best_avg = None, -1.0
        for start in candidates:
            window_samples = [v for t, v in samples if start <= t < start + window]
            if not window_samples:
                continue
            avg = sum(window_samples) / len(window_samples)
            if avg > best_avg:
                best_avg, best_start = avg, start
        return best_start

    def vertical_convert(
        self, input_path: str, output_path: str, strategy: str,
        out_width: int = SHORTS_WIDTH, out_height: int = SHORTS_HEIGHT,
    ) -> None:
        """Convert *input_path* to an *out_width*x*out_height* video.

        strategy='center_crop': scale to fill the target frame, crop the excess width.
        strategy='blur_pad': blurred scaled-fill copy behind an aspect-fit foreground.
        """
        if strategy == "blur_pad":
            chain = (
                f"[0:v]scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
                f"crop={out_width}:{out_height},gblur=sigma=20[bg];"
                f"[0:v]scale={out_width}:{out_height}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
            )
        else:
            chain = (
                f"[0:v]scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
                f"crop={out_width}:{out_height}"
            )
        filter_complex = f"{finalize_filter(chain)}[vout]"
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
        self, input_path: str, output_path: str, duration: float, direction: str, pan: bool,
        out_width: int = SHORTS_WIDTH, out_height: int = SHORTS_HEIGHT,
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
        upscale_dim = out_width * 4
        vf = finalize_filter(
            f"scale={upscale_dim}:-2:flags=lanczos,"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={out_width}x{out_height}:fps={fps}"
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
            "-vf", finalize_filter(f"setpts=PTS/{speed_factor}"),
            "-an",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_speed_ramp(factor={speed_factor}) → {output_path!r}")

    def generate_punch_card(
        self, output_path: str, text: str, duration: float,
        out_width: int = SHORTS_WIDTH, out_height: int = SHORTS_HEIGHT,
    ) -> None:
        """Render a *duration*-second full-frame punch card: theme-dark
        background, huge bold centered white text, with a quick scale-in.

        drawtext is not compiled into this project's bundled ffmpeg build
        (only libass/subtitles is) — verified via `ffmpeg -filters`, which
        lists `subtitles`/`ass` but not `drawtext`. So the card is built as
        a solid-color lavfi source with a single ASS Dialogue line burned
        in via the same subtitles= filter (and the same cwd + bare-filename
        discipline) used by burn_captions. The scale-in is an ASS \\t
        transform on \\fscx/\\fscy rather than a second zoompan pass — ASS
        gives sub-pixel-accurate scaling directly, and unlike drawtext its
        Text field needs no colon/quote escaping (only backslash and the
        {}  override-tag delimiters), since Text is the last field on the
        Dialogue line and captures everything after it verbatim.
        """
        escaped = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
        fps = 30
        ass_content = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {out_width}\n"
            f"PlayResY: {out_height}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n"
            "YCbCr Matrix: TV.601\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Punch,{_PUNCH_FONT_NAME},120,&H00FFFFFF,&H000000FF,"
            "&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,60,60,0,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,{self._format_punch_duration(duration)},Punch,,0,0,0,,"
            f"{{\\fscx70\\fscy70\\t(0,{_PUNCH_SCALE_IN_MS},\\fscx100\\fscy100)}}{escaped}\n"
        )
        ass_path = f"{output_path}.card.ass"
        Path(ass_path).write_text(ass_content, encoding="utf-8")

        ass_dir = os.path.dirname(ass_path) or "."
        ass_name = os.path.basename(ass_path)
        cmd = [
            self._ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c={_PUNCH_CARD_BG}:s={out_width}x{out_height}:d={duration}:r={fps}",
            "-vf", finalize_filter(f"subtitles={ass_name}"),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            os.path.abspath(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=ass_dir)
        self._check(result, f"generate_punch_card → {output_path!r}")

    @staticmethod
    def _format_punch_duration(seconds: float) -> str:
        seconds = max(0.0, seconds)
        total_cs = round(seconds * 100)
        hours, rem = divmod(total_cs, 360000)
        minutes, rem = divmod(rem, 6000)
        secs, cs = divmod(rem, 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"

    def _warn_on_sar_mismatch(self, input_paths: list[str]) -> None:
        """Defensive tripwire, not a hard check: ffprobe each segment's SAR
        and log a warning if any isn't exactly 1:1. Every segment-producing
        path in this module routes through finalize_filter, which should
        make this impossible — but if a future filter path is ever added
        without going through it, this turns the failure into an early
        warning in shorts_log.txt instead of a silent crash at concat time."""
        for path in input_paths:
            try:
                result = subprocess.run(
                    [
                        self._ffprobe, "-v", "error",
                        "-select_streams", "v:0",
                        "-show_entries", "stream=sample_aspect_ratio",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        path,
                    ],
                    capture_output=True, text=True,
                )
                sar = result.stdout.strip()
            except Exception as exc:
                _log.info("_warn_on_sar_mismatch: SAR probe failed for %s (%s)", path, exc)
                continue
            if sar and sar != "1:1":
                _log.warning(
                    "concat_segments_video_only: segment %s has SAR %s (expected 1:1) — "
                    "concat may reject this batch; check its filter chain routes through "
                    "finalize_filter",
                    path, sar,
                )

    def concat_segments_video_only(self, input_paths: list[str], output_path: str) -> None:
        """Concatenate already-vertical, already-Ken-Burns'd segment videos (video only)."""
        self._warn_on_sar_mismatch(input_paths)
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
        self,
        voice_path: str,
        music_path: str,
        video_duration: float,
        output_path: str,
        music_volume_db: float | None = None,
    ) -> None:
        """Loop/trim *music_path* to *video_duration*, duck it under
        *voice_path* via sidechaincompress, and write the mixed result to
        *output_path* as a standalone audio file — the caller (assemble_short)
        passes this into mux_shorts_audio exactly as it would the raw voice
        track, so that method's -map discipline never needs to change.

        *music_volume_db* defaults to the shared ducking module's baseline
        (the same value Slideshow/Clipstory use) when not given."""
        from docu_studio.common.audio_ducking import MUSIC_BASELINE_DB, build_ducking_filtergraph

        filter_complex = build_ducking_filtergraph(
            video_duration,
            music_baseline_db=MUSIC_BASELINE_DB if music_volume_db is None else music_volume_db,
        )
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
