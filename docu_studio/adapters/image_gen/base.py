"""ImageGenProvider ABC — text-to-image generation, distinct from PhotoProvider
(docu_studio/adapters/photos/base.py). A search returns a pool of candidates to
choose from; text-to-image produces exactly one image per prompt, so there is no
candidate-pool concept here."""
from __future__ import annotations

from abc import ABC, abstractmethod


class ImageGenProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        """Generate one image matching *prompt*, sized as close to *width* x
        *height* as the provider supports, and return raw image bytes (PNG/JPEG).
        Raises on failure — callers decide fallback behavior."""
