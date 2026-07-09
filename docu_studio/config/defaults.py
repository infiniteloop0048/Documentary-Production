"""Application-wide defaults. No hardcoded values anywhere else."""
from typing import Final

DEFAULT_WPM: Final[int] = 150
DEFAULT_LLM_MODEL_SCRIPT: Final[str] = "claude-sonnet-4-6"
DEFAULT_LLM_MODEL_KEYWORDS: Final[str] = "claude-haiku-4-5-20251001"
DEFAULT_TTS_PROVIDER: Final[str] = "gtts"
DEFAULT_FOOTAGE_PROVIDERS: Final[list[str]] = ["pexels", "pixabay"]
DEFAULT_LLM_PROVIDER: Final[str] = "Anthropic"
DEFAULT_LLM_MODEL: Final[str] = "claude-sonnet-4-5"
DEFAULT_DEEPGRAM_VOICE: Final[str] = "aura-asteria-en"
DEFAULT_FOOTAGE_SHORTAGE_STRATEGY: Final[str] = "loop"
DEFAULT_FOOTAGE_FALLBACK2: Final[str] = "none"
DEFAULT_MUSIC_PROVIDER: Final[str] = "local"
