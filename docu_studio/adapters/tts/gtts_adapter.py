"""gTTS adapter — free, no API key required."""
from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

import imageio_ffmpeg  # type: ignore[import-untyped]
from gtts import gTTS  # type: ignore[import-untyped]

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_BACKOFF = [3.0, 6.0, 12.0, 20.0, 30.0]

# gTTS enforces a hard 100-char-per-request limit (gtts.tts.GOOGLE_TTS_MAX_CHARS)
# on Google's TTS backend, so any narration over 100 chars — virtually every
# Shorts script — gets split into several independent HTTP requests. Each
# response is synthesized as its own standalone utterance and carries its own
# ~250-350ms leading/trailing silence; gTTS's own tts.save() just pastes the
# raw per-request MP3 bytes together (see gtts.tts.TTS.write_to_fp), so those
# silences stack into audible ~500-700ms dead-air gaps at every sentence
# boundary (confirmed via ffmpeg silencedetect across 3 real generations).
# Threshold/pad values below were verified against real gTTS output: -45dB
# correctly separates all measured silences (~280-350ms) from real speech
# without false-triggering mid-word, and the 80ms pad was checked against a
# chunk ending in a soft nasal consonant ("...Pacific Northwest coastline")
# to confirm the natural decay tail survives intact — only the flat silence
# after it is trimmed.
_SILENCE_THRESHOLD_DB = "-45dB"
_SILENCE_PAD_SECONDS = 0.08
_MIN_NONSILENT_SECONDS = 0.02
_SILENCE_WINDOW_SECONDS = 0.02


def _trim_silence_filter() -> str:
    """ffmpeg 'silenceremove' filter string: strips the leading silence
    period and all trailing silence, keeping a small fixed pad at each end.

    start_periods=1 / stop_periods=-1 constrain trimming to only the very
    first and very last silence runs — silence in the *middle* of a chunk
    (natural word-boundary pauses) is untouched regardless of duration.
    """
    return (
        f"silenceremove="
        f"start_periods=1:start_threshold={_SILENCE_THRESHOLD_DB}:"
        f"start_silence={_SILENCE_PAD_SECONDS}:start_duration={_MIN_NONSILENT_SECONDS}:"
        f"stop_periods=-1:stop_threshold={_SILENCE_THRESHOLD_DB}:"
        f"stop_silence={_SILENCE_PAD_SECONDS}:stop_duration={_MIN_NONSILENT_SECONDS}:"
        f"detection=rms:window={_SILENCE_WINDOW_SECONDS}"
    )


class GTTSAdapter(TTSProvider):
    def __init__(self) -> None:
        self._ffmpeg = FFmpegWrapper()
        self._ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()

    def synthesize(self, text: str, output_path: str) -> float:
        last_exc: Exception | None = None
        for attempt in range(len(_BACKOFF)):
            try:
                tts = gTTS(text=text, lang="en", slow=False)
                self._synthesize_trimmed(tts, output_path)
                return self._ffmpeg.get_duration(output_path)
            except (ConnectionResetError, ConnectionError) as exc:
                last_exc = exc
                if attempt < len(_BACKOFF) - 1:
                    time.sleep(_BACKOFF[attempt])
        raise RuntimeError(
            "TTS failed: gTTS could not connect after 5 attempts. "
            "Please check your internet connection or switch to a different TTS provider in Settings."
        ) from last_exc

    def _synthesize_trimmed(self, tts: gTTS, output_path: str) -> None:
        """Fetch each of gTTS's per-request audio chunks, trim each one's
        silence down to a small consistent pad, and join them with a real
        decode+re-encode concat — unlike gTTS's own tts.save(), which pastes
        the raw per-request MP3 bytes together and leaves every chunk's
        independent leading/trailing silence stacked into an audible gap.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            raw_paths: list[Path] = []
            for idx, decoded in enumerate(tts.stream()):
                raw_path = tmp / f"chunk_{idx:02d}_raw.mp3"
                raw_path.write_bytes(decoded)
                raw_paths.append(raw_path)

            if not raw_paths:
                raise RuntimeError("gTTS returned no audio chunks.")

            if len(raw_paths) == 1:
                # ffmpeg writes straight to output_path — avoids relying on a
                # same-filesystem rename, since the temp dir and the caller's
                # output_path can be on different mounts (e.g. tmpfs vs disk).
                self._trim_chunk(str(raw_paths[0]), output_path)
                return

            trimmed_paths: list[Path] = []
            for idx, raw_path in enumerate(raw_paths):
                trimmed_path = tmp / f"chunk_{idx:02d}_trimmed.mp3"
                self._trim_chunk(str(raw_path), str(trimmed_path))
                trimmed_paths.append(trimmed_path)

            self._concat_chunks(trimmed_paths, output_path)

    def _trim_chunk(self, input_path: str, output_path: str) -> None:
        result = subprocess.run(
            [
                self._ffmpeg_bin, "-y",
                "-i", input_path,
                "-af", _trim_silence_filter(),
                output_path,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gTTS chunk silence-trim failed: {result.stderr}")

    def _concat_chunks(self, chunk_paths: list[Path], output_path: str) -> None:
        """Decode+re-encode concat via the ffmpeg concat demuxer (not raw
        byte-paste) so the joins between trimmed chunks are clean MP3 frames."""
        list_file = chunk_paths[0].parent / "concat_list.txt"
        list_file.write_text(
            "\n".join(f"file '{p.name}'" for p in chunk_paths), encoding="utf-8"
        )
        result = subprocess.run(
            [
                self._ffmpeg_bin, "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c:a", "libmp3lame", "-q:a", "2",
                output_path,
            ],
            capture_output=True, text=True, cwd=str(chunk_paths[0].parent),
        )
        if result.returncode != 0:
            raise RuntimeError(f"gTTS chunk concat failed: {result.stderr}")
