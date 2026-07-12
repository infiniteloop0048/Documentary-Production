"""Configuration for a single Slideshow generation run."""
from __future__ import annotations

from dataclasses import dataclass

SLIDESHOW_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
SLIDESHOW_DEFAULT_ASPECT = "9:16"


@dataclass
class SlideshowConfig:
    script_text: str
    image_paths: list[str]
    aspect_ratio: str = SLIDESHOW_DEFAULT_ASPECT
    transition: str = "cut"
    vignette: bool = False
    grain: bool = False
    captions: bool = False
    music_enabled: bool = False
    music_provider: str = "jamendo"
    music_folder: str = ""
    jamendo_client_id: str = ""

    def __post_init__(self) -> None:
        if not self.script_text.strip():
            raise ValueError("script_text must not be empty")
        if not self.image_paths:
            raise ValueError("image_paths must not be empty")
        if self.aspect_ratio not in SLIDESHOW_ASPECT_DIMENSIONS:
            raise ValueError(
                f"aspect_ratio must be one of {sorted(SLIDESHOW_ASPECT_DIMENSIONS)}, "
                f"got {self.aspect_ratio!r}"
            )
        if self.transition not in ("cut", "crossfade"):
            raise ValueError(
                f"transition must be one of ('cut', 'crossfade'), got {self.transition!r}"
            )
        if self.music_provider not in ("jamendo", "local_folder"):
            raise ValueError(
                f"music_provider must be one of ('jamendo', 'local_folder'), "
                f"got {self.music_provider!r}"
            )

    @property
    def output_dimensions(self) -> tuple[int, int]:
        return SLIDESHOW_ASPECT_DIMENSIONS[self.aspect_ratio]
