"""Persistent settings for docu_studio.

Non-secret fields are stored as JSON in the OS config directory.
API keys are stored via keyring (OS-native secret store) and never written to disk.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import keyring

from docu_studio.config.defaults import (
    DEFAULT_DEEPGRAM_VOICE,
    DEFAULT_FOOTAGE_FALLBACK2,
    DEFAULT_FOOTAGE_PROVIDERS,
    DEFAULT_FOOTAGE_SHORTAGE_STRATEGY,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_MODEL_KEYWORDS,
    DEFAULT_LLM_MODEL_SCRIPT,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_TTS_PROVIDER,
    DEFAULT_WPM,
)
from docu_studio.platform_layer import config_dir

_KEYRING_SERVICE = "docu_studio"
_KEYRING_DEEPGRAM = "docu_studio_deepgram_key"
_KEYRING_OPENAI = "docu_studio_openai_key"
_KEYRING_OPENROUTER = "docu_studio_openrouter_key"
_KEYRING_GROQ = "docu_studio_groq_key"
_SETTINGS_FILE = "settings.json"


@dataclass
class Settings:
    wpm: int = DEFAULT_WPM
    tts_provider: str = DEFAULT_TTS_PROVIDER
    footage_providers: list[str] = field(default_factory=lambda: list(DEFAULT_FOOTAGE_PROVIDERS))
    llm_model_script: str = DEFAULT_LLM_MODEL_SCRIPT
    llm_model_keywords: str = DEFAULT_LLM_MODEL_KEYWORDS
    output_folder: Optional[str] = None
    llm_provider: str = DEFAULT_LLM_PROVIDER
    llm_model: str = DEFAULT_LLM_MODEL
    deepgram_voice: str = DEFAULT_DEEPGRAM_VOICE
    footage_primary:   str = "pexels"
    footage_fallback:  str = "pixabay"
    footage_fallback2: str = DEFAULT_FOOTAGE_FALLBACK2
    footage_shortage_strategy: str = DEFAULT_FOOTAGE_SHORTAGE_STRATEGY
    llm_custom_model: str = ""

    # --- persistence ---

    def save(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "Settings":
        path = cls._path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()

    # --- keyring helpers ---

    @staticmethod
    def get_key(provider: str) -> str:
        try:
            return keyring.get_password(_KEYRING_SERVICE, provider) or ""
        except Exception:
            return ""

    @staticmethod
    def set_key(provider: str, value: str) -> None:
        try:
            keyring.set_password(_KEYRING_SERVICE, provider, value)
        except Exception:
            logging.warning("keyring unavailable; key for %r not saved", provider)

    # --- internal ---

    @classmethod
    def _path(cls) -> Path:
        return config_dir() / _SETTINGS_FILE
