"""TTSProvider ABC — all pipeline code imports only this interface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: str) -> float:
        """Synthesize *text* to an audio file at *output_path*.

        Returns the duration of the synthesized audio in seconds.
        """
