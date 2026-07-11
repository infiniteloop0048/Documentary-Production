"""Manual image source for Slideshow — Phase 1 only supports a user-supplied
ordered list. Topic-based fetch is Phase 2."""
from __future__ import annotations

from pathlib import Path

_VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class InvalidImageListError(ValueError):
    """Raised when a manual image list fails validation."""


def validate_manual_images(paths: list[str]) -> list[str]:
    """Validate a user-supplied ordered image list.

    Returns the same paths (order preserved) if every entry exists and has
    a recognized image extension. Raises InvalidImageListError with a clear
    message otherwise — this is the fail-fast boundary check, called before
    any TTS synthesis or ffmpeg work starts.
    """
    if not paths:
        raise InvalidImageListError("At least one image is required.")
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise InvalidImageListError(f"Image not found: {p}")
        if path.suffix.lower() not in _VALID_EXTENSIONS:
            raise InvalidImageListError(
                f"Unsupported image format: {p} "
                f"(expected one of {sorted(_VALID_EXTENSIONS)})"
            )
    return list(paths)
