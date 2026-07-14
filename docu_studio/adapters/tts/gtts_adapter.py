"""gTTS adapter — free, no API key required."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from gtts import gTTS  # type: ignore[import-untyped]

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper
from docu_studio.shorts.shorts_tts_join import SilenceTrimParams, trim_and_join

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
_SILENCE_PARAMS = SilenceTrimParams(
    threshold_db="-45dB", pad_seconds=0.08, min_nonsilent_seconds=0.02, window_seconds=0.02,
)


class GTTSAdapter(TTSProvider):
    def __init__(self) -> None:
        self._ffmpeg = FFmpegWrapper()

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
        """Fetch each of gTTS's per-request audio chunks and hand them to the
        shared trim_and_join utility — unlike gTTS's own tts.save(), which
        pastes the raw per-request MP3 bytes together and leaves every
        chunk's independent leading/trailing silence stacked into an
        audible gap.
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

            trim_and_join(raw_paths, output_path, _SILENCE_PARAMS)
