"""Adapter-agnostic silence-trim + join for per-sentence TTS audio.

Per-sentence TTS (synthesize() called once per sentence instead of once for
the whole script) means each sentence's own audio file carries its own
leading/trailing silence. Naively concatenating those files stacks that
silence into an audible gap at every sentence boundary — the same failure
mode Task 2 fixed for gTTS's own internal >100-char chunking, generalized
here to work across sentence boundaries for any TTS adapter's output.

Pure ffmpeg-subprocess work on already-synthesized audio files — no adapter
imports here, so any adapter's per-sentence output can be passed through
unmodified. GTTSAdapter's own internal chunk-trimming (for its 100-char
request limit) is a separate, adapter-specific concern and stays in
gtts_adapter.py; this module only knows about whole audio files.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg  # type: ignore[import-untyped]

_ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()


@dataclass(frozen=True)
class SilenceTrimParams:
    """Silence-detection parameters for trim_silence/trim_and_join.

    Defaults match Task 2's gTTS-calibrated values. Other adapters must NOT
    reuse these without their own real-audio silencedetect calibration pass
    — different TTS vendors/vocoders produce different natural silence
    characteristics (see Task 4 Phase 2, which calibrates ElevenLabs' and
    Deepgram's own parameters rather than assuming these transfer).
    """
    threshold_db: str = "-45dB"
    pad_seconds: float = 0.08
    min_nonsilent_seconds: float = 0.02
    window_seconds: float = 0.02


def _trim_silence_filter(params: SilenceTrimParams) -> str:
    """ffmpeg 'silenceremove' filter string: strips the leading silence
    period and all trailing silence, keeping a small fixed pad at each end.

    start_periods=1 / stop_periods=-1 constrain trimming to only the very
    first and very last silence runs — silence in the *middle* of a clip
    (natural word-boundary pauses) is untouched regardless of duration.
    """
    return (
        f"silenceremove="
        f"start_periods=1:start_threshold={params.threshold_db}:"
        f"start_silence={params.pad_seconds}:start_duration={params.min_nonsilent_seconds}:"
        f"stop_periods=-1:stop_threshold={params.threshold_db}:"
        f"stop_silence={params.pad_seconds}:stop_duration={params.min_nonsilent_seconds}:"
        f"detection=rms:window={params.window_seconds}"
    )


def trim_silence(input_path: str, output_path: str, params: SilenceTrimParams) -> None:
    """Trim *input_path*'s leading/trailing silence down to *params*'s pad,
    writing the result to *output_path*."""
    result = subprocess.run(
        [
            _ffmpeg_bin, "-y",
            "-i", input_path,
            "-af", _trim_silence_filter(params),
            output_path,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Audio silence-trim failed: {result.stderr}")


def concat_audio(input_paths: list[Path], output_path: str) -> None:
    """Decode+re-encode concat via the ffmpeg concat demuxer (not raw
    byte-paste) so the joins between *input_paths* are clean MP3 frames.

    *input_paths* are joined in the exact order given — callers own sentence
    ordering (e.g. sorting concurrently-synthesized sentence audio back into
    script order before calling this); this function never reorders."""
    list_file = input_paths[0].parent / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{p.name}'" for p in input_paths), encoding="utf-8"
    )
    result = subprocess.run(
        [
            _ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c:a", "libmp3lame", "-q:a", "2",
            output_path,
        ],
        capture_output=True, text=True, cwd=str(input_paths[0].parent),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Audio concat failed: {result.stderr}")


def trim_and_join(
    input_paths: list[Path], output_path: str, params: SilenceTrimParams,
) -> None:
    """Trim each of *input_paths*' leading/trailing silence to *params*'s
    pad, then join them in the given order into *output_path*.

    A single input trims directly to *output_path* — no concat demuxer
    round-trip needed when there's nothing to join."""
    if not input_paths:
        raise RuntimeError("trim_and_join: no audio clips given.")

    if len(input_paths) == 1:
        trim_silence(str(input_paths[0]), output_path, params)
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        trimmed_paths: list[Path] = []
        for idx, input_path in enumerate(input_paths):
            trimmed_path = tmp / f"clip_{idx:03d}_trimmed.mp3"
            trim_silence(str(input_path), str(trimmed_path), params)
            trimmed_paths.append(trimmed_path)
        concat_audio(trimmed_paths, output_path)
