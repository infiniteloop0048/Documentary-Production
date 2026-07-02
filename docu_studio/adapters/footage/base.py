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


class FootageProvider(ABC):
    @abstractmethod
    def search(self, keywords: list[str], min_duration: float, page: int = 1) -> list[FootageClip]:
        """Return clips matching *keywords*, each at least *min_duration* seconds long."""
