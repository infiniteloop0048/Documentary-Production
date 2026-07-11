"""Ken Burns motion selection for Slideshow.

Phase 1 supports classic zoom in/out only. Pan, rotation, and mixed-random
variants are Phase 3.
"""
from __future__ import annotations

_DIRECTIONS = ("in", "out")


def direction_for_index(index: int) -> str:
    """Alternate zoom-in/zoom-out per image so consecutive segments don't
    all zoom the same way."""
    return _DIRECTIONS[index % 2]
