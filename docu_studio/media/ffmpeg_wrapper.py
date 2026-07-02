"""FFmpeg wrapper — all subprocess calls for media operations live here."""
from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg  # type: ignore[import-untyped]

from docu_studio import platform_layer


class FFmpegError(Exception):
    """Raised when an FFmpeg or ffprobe subprocess exits with a non-zero code."""


class FFmpegWrapper:
    def __init__(self) -> None:
        self._ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self._ffprobe = platform_layer.ffprobe_exe()

    # --- public API ---

    def get_duration(self, path: str) -> float:
        """Return the duration of *path* in seconds via ffprobe."""
        result = subprocess.run(
            [
                self._ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
        )
        self._check(result, f"get_duration({path!r})")
        return float(result.stdout.strip())

    def trim_clip(self, input_path: str, start: float, duration: float, output_path: str) -> None:
        """Trim *input_path* starting at *start* for *duration* seconds → *output_path*.

        Re-encodes so the output duration matches *duration* exactly (no keyframe snapping).
        """
        result = subprocess.run(
            [
                self._ffmpeg, "-y",
                "-ss", str(start),
                "-t", str(duration),
                "-i", input_path,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                output_path,
            ],
            capture_output=True,
            text=True,
        )
        self._check(result, f"trim_clip({input_path!r})")

    def concat_clips(self, input_paths: list[str], output_path: str) -> None:
        """Concatenate *input_paths* into *output_path*.

        Re-encodes to 1920x1080@30fps via filter_complex so clips with different
        resolutions, frame-rates, or stream counts (e.g. video-only) are handled
        correctly without PTS corruption from the concat demuxer.
        """
        n = len(input_paths)
        scale_parts = [f"[{i}:v]fps=30,scale=1920:1080[v{i}]" for i in range(n)]
        concat_inputs = "".join(f"[v{i}]" for i in range(n))
        filter_complex = ";".join(scale_parts) + f";{concat_inputs}concat=n={n}:v=1:a=0[vout]"

        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_clips → {output_path!r}")

    def concat_scenes(self, input_paths: list[str], output_path: str) -> None:
        """Concatenate muxed scene videos (video+audio) into a single file.

        Uses filter_complex so clips with differing resolutions/frame-rates
        are normalised to 1920×1080@30fps before concatenation.
        """
        n = len(input_paths)
        scale_parts = ";".join(f"[{i}:v]fps=30,scale=1920:1080[v{i}]" for i in range(n))
        interleaved = "".join(f"[v{i}][{i}:a]" for i in range(n))
        filter_complex = (
            scale_parts
            + f";{interleaved}concat=n={n}:v=1:a=1[outv][outa]"
        )
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
        self._check(result, f"concat_scenes → {output_path!r}")

    def mux_audio_video(self, video_path: str, audio_path: str, output_path: str) -> None:
        """Mux *video_path* and *audio_path* into *output_path*, mapping shortest stream.

        Explicitly maps video from *video_path* and audio from *audio_path* only.
        Without explicit -map, ffmpeg auto-selects one stream of each type across
        ALL inputs — if the source footage clip itself has an audio track, ffmpeg
        can pick that track instead of (or in place of) the TTS audio, so the
        final mux ends up with the wrong (or double) audio.
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
        self._check(result, f"mux_audio_video → {output_path!r}")

    def has_audio_stream(self, path: str) -> bool:
        """Return True if *path* contains at least one audio stream (via ffprobe)."""
        result = subprocess.run(
            [
                self._ffprobe,
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
        )
        self._check(result, f"has_audio_stream({path!r})")
        return bool(result.stdout.strip())

    # --- internal ---

    @staticmethod
    def _check(result: subprocess.CompletedProcess, label: str) -> None:
        if result.returncode != 0:
            raise FFmpegError(
                f"FFmpeg/ffprobe error in {label}: {result.stderr.strip()}"
            )
