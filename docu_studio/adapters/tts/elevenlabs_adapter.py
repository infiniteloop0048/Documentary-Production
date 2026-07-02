"""ElevenLabs TTS adapter — paid, requires API key."""
from __future__ import annotations

from pathlib import Path

from elevenlabs import ElevenLabs  # type: ignore[import-untyped]

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.media.ffmpeg_wrapper import FFmpegWrapper
from docu_studio.retry import retry


class ElevenLabsAdapter(TTSProvider):
    def __init__(self, api_key: str, voice_id: str = "Rachel") -> None:
        self._client = ElevenLabs(api_key=api_key)
        self._voice_id = voice_id
        self._ffmpeg = FFmpegWrapper()

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def synthesize(self, text: str, output_path: str) -> float:
        audio = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
        )
        Path(output_path).write_bytes(b"".join(audio))
        return self._ffmpeg.get_duration(output_path)
