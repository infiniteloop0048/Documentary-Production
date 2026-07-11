"""Unit tests for SlideshowConfig — pure dataclass validation, no I/O."""
from __future__ import annotations

import pytest

from docu_studio.slideshow.slideshow_config import (
    SLIDESHOW_ASPECT_DIMENSIONS,
    SLIDESHOW_DEFAULT_ASPECT,
    SlideshowConfig,
)


class TestSlideshowConfig:
    def test_valid_config_defaults_to_9_16(self) -> None:
        cfg = SlideshowConfig(script_text="Hello world.", image_paths=["/a.jpg"])
        assert cfg.aspect_ratio == SLIDESHOW_DEFAULT_ASPECT
        assert cfg.output_dimensions == (1080, 1920)

    def test_16_9_dimensions(self) -> None:
        cfg = SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], aspect_ratio="16:9")
        assert cfg.output_dimensions == (1920, 1080)

    def test_1_1_dimensions(self) -> None:
        cfg = SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], aspect_ratio="1:1")
        assert cfg.output_dimensions == (1080, 1080)

    def test_empty_script_text_raises(self) -> None:
        with pytest.raises(ValueError, match="script_text"):
            SlideshowConfig(script_text="   ", image_paths=["/a.jpg"])

    def test_empty_image_paths_raises(self) -> None:
        with pytest.raises(ValueError, match="image_paths"):
            SlideshowConfig(script_text="Hi.", image_paths=[])

    def test_unknown_aspect_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="aspect_ratio"):
            SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], aspect_ratio="4:3")

    def test_all_known_aspect_ratios_present(self) -> None:
        assert set(SLIDESHOW_ASPECT_DIMENSIONS) == {"9:16", "16:9", "1:1"}
