"""Factory for TTS adapters."""
from __future__ import annotations

from docu_studio.adapters.tts.base import TTSProvider


def build_tts(provider: str, api_key: str, voice: str = "") -> TTSProvider:
    p = (provider or "").lower()
    if p == "elevenlabs":
        from docu_studio.adapters.tts.elevenlabs_adapter import ElevenLabsAdapter
        return ElevenLabsAdapter(api_key=api_key, voice_id=voice or "Rachel")
    if p == "deepgram":
        from docu_studio.adapters.tts.deepgram_adapter import DeepgramAdapter
        return DeepgramAdapter(api_key=api_key, voice=voice or "aura-asteria-en")
    from docu_studio.adapters.tts.gtts_adapter import GTTSAdapter
    return GTTSAdapter()
