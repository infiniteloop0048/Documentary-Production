"""gTTS adapter — free, no API key required."""
from __future__ import annotations

import time

from gtts import gTTS  # type: ignore[import-untyped]

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper

_BACKOFF = [3.0, 6.0, 12.0, 20.0, 30.0]


class GTTSAdapter(TTSProvider):
    def __init__(self) -> None:
        self._ffmpeg = FFmpegWrapper()

    def synthesize(self, text: str, output_path: str) -> float:
        last_exc: Exception | None = None
        for attempt in range(len(_BACKOFF)):
            try:
                tts = gTTS(text=text, lang="en", slow=False)
                tts.save(output_path)
                return self._ffmpeg.get_duration(output_path)
            except (ConnectionResetError, ConnectionError) as exc:
                last_exc = exc
                if attempt < len(_BACKOFF) - 1:
                    time.sleep(_BACKOFF[attempt])
        raise RuntimeError(
            "TTS failed: gTTS could not connect after 5 attempts. "
            "Please check your internet connection or switch to a different TTS provider in Settings."
        ) from last_exc
