"""Configuration for a single Shorts/Reels generation run."""
from __future__ import annotations

from dataclasses import dataclass

from docu_studio.adapters.image_gen.factory import IMAGE_GEN_PRESETS
from docu_studio.common.captions import CAPTION_STYLES, DEFAULT_CAPTION_STYLE

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

SHORTS_FOOTAGE_SOURCES = ("video", "image", "ai_image")
SHORTS_DEFAULT_FOOTAGE_SOURCE = "video"
SHORTS_DEFAULT_AI_IMAGE_MODEL = "replicate_flux_schnell"

# 1-1.5s cinematic hold after the last word: video and music continue, no
# voice, no new captions (nothing left to caption) — a beat of silence
# before the hard cut instead of ending mid-word.
SHORTS_ENDING_HOLD_SECONDS = 1.2

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
    footage_source: str = SHORTS_DEFAULT_FOOTAGE_SOURCE
    ai_image_model: str = SHORTS_DEFAULT_AI_IMAGE_MODEL
    ai_story_continuity: bool = True
    duration_seconds: int = SHORTS_DEFAULT_DURATION
    captions_enabled: bool = True
    caption_style: str = DEFAULT_CAPTION_STYLE
    music_enabled: bool = True
    music_volume_db: float = SHORTS_DEFAULT_MUSIC_VOLUME_DB
    beat_sync_enabled: bool = True
    speed_ramp_enabled: bool = True
    loop_revisit_enabled: bool = True
    cinematic_ending_enabled: bool = True

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
        if self.footage_source not in SHORTS_FOOTAGE_SOURCES:
            raise ValueError(
                f"footage_source must be one of {SHORTS_FOOTAGE_SOURCES}, "
                f"got {self.footage_source!r}"
            )
        if self.ai_image_model not in IMAGE_GEN_PRESETS:
            raise ValueError(
                f"ai_image_model must be one of {sorted(IMAGE_GEN_PRESETS)}, "
                f"got {self.ai_image_model!r}"
            )
        if not (SHORTS_MUSIC_VOLUME_MIN_DB <= self.music_volume_db <= SHORTS_MUSIC_VOLUME_MAX_DB):
            raise ValueError(
                f"music_volume_db must be between {SHORTS_MUSIC_VOLUME_MIN_DB} and "
                f"{SHORTS_MUSIC_VOLUME_MAX_DB}, got {self.music_volume_db}"
            )
        if self.caption_style not in CAPTION_STYLES:
            raise ValueError(
                f"caption_style must be one of {CAPTION_STYLES}, got {self.caption_style!r}"
            )

    @property
    def output_dimensions(self) -> tuple[int, int]:
        return SHORTS_ASPECT_DIMENSIONS[self.aspect_ratio]
