"""PhotoProvider ABC and PhotoResult dataclass — still-image search, distinct
from FootageProvider/FootageClip (docu_studio/adapters/footage/base.py),
which are duration-oriented and don't fit photos."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PhotoResult:
    url: str
    width: int
    height: int
    # Stable provider-native photo ID (Pexels/Pixabay numeric id, as a
    # string). "" when a provider/call site doesn't populate it. Callers
    # that need to dedupe should prefer this over `url` — the same
    # underlying photo can be returned with a different URL across separate
    # search calls (e.g. different size variants).
    photo_id: str = ""


class PhotoProvider(ABC):
    @abstractmethod
    def search(self, query: str, page: int = 1) -> list[PhotoResult]:
        """Return photos matching *query*."""
