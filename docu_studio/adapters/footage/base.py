"""FootageProvider ABC and FootageClip dataclass."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FootageClip:
    url: str
    duration: float
    width: int
    height: int
    # Stable provider-native video ID (e.g. Pexels/Pixabay/Coverr numeric id, as a
    # string). "" when a provider/call site doesn't populate it. Callers that need
    # to dedupe should prefer this over `url` — the same underlying clip can be
    # returned with different signed/tokenized download URLs across separate
    # search calls, which would defeat url-based dedup.
    clip_id: str = ""


class FootageProvider(ABC):
    @abstractmethod
    def search(self, keywords: list[str], min_duration: float, page: int = 1) -> list[FootageClip]:
        """Return clips matching *keywords*, each at least *min_duration* seconds long."""
