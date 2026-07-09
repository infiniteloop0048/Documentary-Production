"""Configuration for a single Shorts/Reels generation run."""
from __future__ import annotations

from dataclasses import dataclass

SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_MIN_DURATION = 15
SHORTS_MAX_DURATION = 60
SHORTS_DEFAULT_DURATION = 30
SHORTS_WPM = 170


@dataclass
class ShortsConfig:
    topic: str
    duration_seconds: int = SHORTS_DEFAULT_DURATION
    captions_enabled: bool = True
    music_enabled: bool = True

    def __post_init__(self) -> None:
        if not (SHORTS_MIN_DURATION <= self.duration_seconds <= SHORTS_MAX_DURATION):
            raise ValueError(
                f"duration_seconds must be between {SHORTS_MIN_DURATION} and "
                f"{SHORTS_MAX_DURATION}, got {self.duration_seconds}"
            )
