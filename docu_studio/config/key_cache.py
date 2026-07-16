"""In-memory cache for keyring secrets — warmed in a daemon thread at startup."""
from __future__ import annotations

import threading

import keyring

_KEYRING_SERVICE = "docu_studio"

_USERNAMES = [
    "docu_studio_anthropic",
    "docu_studio_openai",
    "docu_studio_openrouter",
    "docu_studio_groq",
    "docu_studio_elevenlabs",
    "docu_studio_deepgram_key",
    "docu_studio_pexels",
    "docu_studio_pixabay",
    "docu_studio_coverr",
    "docu_studio_serper",
    "docu_studio_jamendo",
]

_cache: dict[str, str] = {}
_loaded = threading.Event()


def warm_cache() -> None:
    """Fetch all secrets once. Call in a daemon thread at app startup."""
    for username in _USERNAMES:
        try:
            _cache[username] = keyring.get_password(_KEYRING_SERVICE, username) or ""
        except Exception:
            _cache[username] = ""
    _loaded.set()


def get(username: str) -> str:
    """Return cached value, waiting for the warm-up pass if it's still running
    instead of each caller making its own redundant live keyring round-trip
    (a single get_settings() call can check up to 11 keys)."""
    if not _loaded.is_set() and not _loaded.wait(timeout=5.0):
        try:
            return keyring.get_password(_KEYRING_SERVICE, username) or ""
        except Exception:
            return ""
    return _cache.get(username, "")


def set_key(username: str, value: str) -> None:
    """Write to cache + keyring. Safe to call from background thread."""
    _cache[username] = value
    try:
        keyring.set_password(_KEYRING_SERVICE, username, value)
    except Exception:
        pass
