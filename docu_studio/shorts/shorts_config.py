"""Configuration for a single Shorts/Reels generation run."""
from __future__ import annotations

from dataclasses import dataclass

SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_MIN_DURATION = 15
SHORTS_MAX_DURATION = 60
SHORTS_DEFAULT_DURATION = 30
SHORTS_WPM = 170

SHORTS_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (SHORTS_WIDTH, SHORTS_HEIGHT),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
SHORTS_DEFAULT_ASPECT = "9:16"

# Music volume/mix-level: bounds are generous around the ducking module's
# real current baseline (docu_studio.common.audio_ducking.MUSIC_BASELINE_DB)
# so the GUI default reflects unchanged behavior, not a guess.
SHORTS_MUSIC_VOLUME_MIN_DB = -40.0
SHORTS_MUSIC_VOLUME_MAX_DB = 0.0
SHORTS_DEFAULT_MUSIC_VOLUME_DB = -20.0


@dataclass
class ShortsConfig:
    topic: str
    aspect_ratio: str = SHORTS_DEFAULT_ASPECT
    duration_seconds: int = SHORTS_DEFAULT_DURATION
    captions_enabled: bool = True
    music_enabled: bool = True
    music_volume_db: float = SHORTS_DEFAULT_MUSIC_VOLUME_DB
    beat_sync_enabled: bool = True
    speed_ramp_enabled: bool = True
    punch_enabled: bool = True
    loop_revisit_enabled: bool = True

    def __post_init__(self) -> None:
        if not (SHORTS_MIN_DURATION <= self.duration_seconds <= SHORTS_MAX_DURATION):
            raise ValueError(
                f"duration_seconds must be between {SHORTS_MIN_DURATION} and "
                f"{SHORTS_MAX_DURATION}, got {self.duration_seconds}"
            )
        if self.aspect_ratio not in SHORTS_ASPECT_DIMENSIONS:
            raise ValueError(
                f"aspect_ratio must be one of {sorted(SHORTS_ASPECT_DIMENSIONS)}, "
                f"got {self.aspect_ratio!r}"
            )
        if not (SHORTS_MUSIC_VOLUME_MIN_DB <= self.music_volume_db <= SHORTS_MUSIC_VOLUME_MAX_DB):
            raise ValueError(
                f"music_volume_db must be between {SHORTS_MUSIC_VOLUME_MIN_DB} and "
                f"{SHORTS_MUSIC_VOLUME_MAX_DB}, got {self.music_volume_db}"
            )

    @property
    def output_dimensions(self) -> tuple[int, int]:
        return SHORTS_ASPECT_DIMENSIONS[self.aspect_ratio]
