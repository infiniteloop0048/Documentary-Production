"""Deepgram TTS adapter — REST API, returns raw MP3 bytes."""
from __future__ import annotations

from pathlib import Path

import requests

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper
from docu_studio.retry import retry


class DeepgramAdapter(TTSProvider):
    _SPEAK_URL = "https://api.deepgram.com/v1/speak"

    def __init__(self, api_key: str, voice: str = "aura-asteria-en") -> None:
        self._api_key = api_key
        self._voice = voice
        self._ffmpeg = FFmpegWrapper()

    # Deepgram's own rate-limit docs recommend exponential backoff with no
    # documented Retry-After header to honor instead — the same generic
    # strategy ElevenLabsAdapter already uses, so these parameters mirror it
    # rather than inventing different ones without evidence either provider
    # needs them.
    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def synthesize(self, text: str, output_path: str) -> float:
        resp = requests.post(
            f"{self._SPEAK_URL}?model={self._voice}",
            headers={
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"text": text},
            timeout=60,
        )
        resp.raise_for_status()
        Path(output_path).write_bytes(resp.content)
        return self._ffmpeg.get_duration(output_path)
