"""ClipStoryFFmpeg: adds atempo pacing, per-clip resolution normalization, audio
reconciliation (pad/trim-fade), and poster-frame extraction on top of the shared
FFmpegWrapper. Every clip is normalized before mux/concat because uploaded videos
arrive in far more heterogeneous encodings than Shorts/Slideshow's stock footage —
see docs/superpowers/specs/2026-07-13-clipstory-phase1-design.md.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from docu_studio.clipstory.clipstory_pacing import ReconciliationPlan
from docu_studio.common.ffmpeg_finalize import finalize_filter
from docu_studio.media.ffmpeg_wrapper import FFmpegError, FFmpegWrapper

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
            try:
                shutil.copy(input_path, output_path)
            except OSError as exc:
                raise FFmpegError(
                    f"apply_reconciliation(none) → {output_path!r}: {exc}"
                ) from exc

    def extract_poster_frame(self, video_path: str, timestamp: float, output_path: str) -> None:
        result = subprocess.run(
            [self._ffmpeg, "-y", "-ss", str(timestamp), "-i", video_path,
             "-frames:v", "1", "-q:v", "3", output_path],
            capture_output=True, text=True,
        )
        self._check(result, f"extract_poster_frame → {output_path!r}")

    def burn_captions(self, input_path: str, ass_path: str, output_path: str) -> None:
        """Burn *ass_path* (ASS pop-caption subtitles) into *input_path* via
        ffmpeg's subtitles filter. *input_path* is video-only — captions burn
        in per-clip, before narration is muxed, so there's no audio stream to
        preserve at this stage. Same cwd-relative-filename technique as
        SlideshowFFmpeg.burn_captions: ffmpeg's -vf value is parsed by the
        avfilter graph description parser, which splits on unescaped ':' —
        this breaks on any colon in the path. Sidestepping it: run ffmpeg with
        cwd set to the subtitle file's own directory and reference only its
        bare filename in the filter string."""
        ass_dir = os.path.dirname(ass_path) or "."
        ass_name = os.path.basename(ass_path)
        vf = finalize_filter(f"subtitles={ass_name}")
        cmd = [
            self._ffmpeg, "-y",
            "-i", os.path.abspath(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            os.path.abspath(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=ass_dir)
        self._check(result, f"burn_captions → {output_path!r}")

    def mix_music_bed(
        self, voice_path: str, music_path: str, video_duration: float, output_path: str,
    ) -> None:
        """Loop/trim *music_path* to *video_duration*, duck it under
        *voice_path* via sidechaincompress, and write the mixed result to
        *output_path* as a standalone audio file. *voice_path* may be a video
        file with an embedded narration track (e.g. the fully-assembled
        Clip Story output) — ffmpeg's [0:a] reference resolves to that file's
        audio stream automatically, no separate extraction pass needed."""
        from docu_studio.common.audio_ducking import build_ducking_filtergraph

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

    @staticmethod
    def _xfade_offsets(durations: list[float], transition_duration: float) -> list[float]:
        """Return the N-1 ffmpeg `offset=` values for chaining `xfade` across
        N segments of the given *durations*. Each offset is the point in the
        running merged timeline where the next segment's crossfade begins:
        cumulative_duration_so_far - transition_duration. Same cumulative
        technique as SlideshowFFmpeg._xfade_offsets, reimplemented locally
        (Clip Story's crossfade was never a shared-core candidate)."""
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
        """Concatenate already-narration-muxed Clip Story segments with a
        crossfade, chaining ffmpeg's xfade (video) and acrossfade (audio)
        filters together in one filter_complex so video and audio shrink by
        the same overlap at every cut and stay in sync by construction — see
        docs/superpowers/specs/2026-07-13-clipstory-phase2-design.md,
        "the real design fork", for why this differs from Slideshow's
        video-only crossfade (Slideshow never has audio muxed into its
        segments before concat; Clip Story already does). *durations* are
        each segment's actual measured duration (unmodified — unlike
        Slideshow, Clip Story's target duration is the physical trim length,
        not a single narration length to preserve, so a crossfade legitimately
        shortens total output by (n-1) * transition_duration; nothing is
        inflated to compensate). The final xfade stage is finalized through
        setsar=1,format=yuv420p so this path can't reintroduce the SAR
        concat-crash bug."""
        n = len(input_paths)
        if n < 2:
            raise ValueError("concat_segments_with_xfade requires at least 2 segments")
        offsets = self._xfade_offsets(durations, transition_duration)

        fps_stages = ";".join(f"[{i}:v]fps=30[v{i}]" for i in range(n))
        stages = [fps_stages]
        prev_v, prev_a = "[v0]", "[0:a]"
        for i in range(1, n):
            next_v, next_a = f"[v{i}]", f"[{i}:a]"
            is_last = i == n - 1
            out_v = "[vout]" if is_last else f"[x{i}v]"
            out_a = "[aout]" if is_last else f"[x{i}a]"
            v_stage = (
                f"{prev_v}{next_v}xfade=transition=fade:"
                f"duration={transition_duration:.2f}:offset={offsets[i - 1]:.3f}"
            )
            if is_last:
                v_stage = finalize_filter(v_stage)
            v_stage += out_v
            a_stage = f"{prev_a}{next_a}acrossfade=d={transition_duration:.2f}" + out_a
            stages.append(v_stage)
            stages.append(a_stage)
            prev_v, prev_a = f"[x{i}v]", f"[x{i}a]"
        filter_complex = ";".join(stages)

        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_segments_with_xfade → {output_path!r}")

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
        n = len(input_paths)
        scale_parts = ";".join(f"[{i}:v]fps=30[v{i}]" for i in range(n))
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
