"""Unit tests for ShortsConfig bounds validation."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_config import (
    SHORTS_ASPECT_DIMENSIONS,
    SHORTS_DEFAULT_ASPECT,
    SHORTS_DEFAULT_DURATION,
    SHORTS_DEFAULT_MUSIC_VOLUME_DB,
    SHORTS_HEIGHT,
    SHORTS_MAX_DURATION,
    SHORTS_MIN_DURATION,
    SHORTS_MUSIC_VOLUME_MAX_DB,
    SHORTS_MUSIC_VOLUME_MIN_DB,
    SHORTS_WIDTH,
    ShortsConfig,
)


class TestShortsConfig:
    def test_default_construction_is_valid(self) -> None:
        cfg = ShortsConfig(topic="Ocean facts")
        assert cfg.topic == "Ocean facts"
        assert cfg.duration_seconds == SHORTS_DEFAULT_DURATION

    def test_accepts_min_and_max_bounds(self) -> None:
        ShortsConfig(topic="x", duration_seconds=SHORTS_MIN_DURATION)
        ShortsConfig(topic="x", duration_seconds=SHORTS_MAX_DURATION)

    def test_rejects_below_minimum(self) -> None:
        with pytest.raises(ValueError):
            ShortsConfig(topic="x", duration_seconds=SHORTS_MIN_DURATION - 1)

    def test_rejects_above_maximum(self) -> None:
        with pytest.raises(ValueError):
            ShortsConfig(topic="x", duration_seconds=SHORTS_MAX_DURATION + 1)

    def test_aspect_constants_are_vertical(self) -> None:
        assert SHORTS_WIDTH == 1080
        assert SHORTS_HEIGHT == 1920

    def test_new_feature_toggles_default_to_true(self) -> None:
        cfg = ShortsConfig(topic="x")
        assert cfg.beat_sync_enabled is True
        assert cfg.speed_ramp_enabled is True
        assert cfg.punch_enabled is True
        assert cfg.loop_revisit_enabled is True

    def test_feature_toggles_can_be_disabled_individually(self) -> None:
        cfg = ShortsConfig(topic="x", beat_sync_enabled=False, punch_enabled=False)
        assert cfg.beat_sync_enabled is False
        assert cfg.speed_ramp_enabled is True
        assert cfg.punch_enabled is False
        assert cfg.loop_revisit_enabled is True


class TestShortsAspectRatio:
    def test_default_aspect_is_9_16(self) -> None:
        cfg = ShortsConfig(topic="x")
        assert cfg.aspect_ratio == SHORTS_DEFAULT_ASPECT
        assert cfg.output_dimensions == (1080, 1920)

    def test_16_9_dimensions(self) -> None:
        cfg = ShortsConfig(topic="x", aspect_ratio="16:9")
        assert cfg.output_dimensions == (1920, 1080)

    def test_1_1_dimensions(self) -> None:
        cfg = ShortsConfig(topic="x", aspect_ratio="1:1")
        assert cfg.output_dimensions == (1080, 1080)

    def test_unknown_aspect_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="aspect_ratio"):
            ShortsConfig(topic="x", aspect_ratio="4:3")

    def test_all_known_aspect_ratios_present(self) -> None:
        assert set(SHORTS_ASPECT_DIMENSIONS) == {"9:16", "16:9", "1:1"}

    def test_default_aspect_dimensions_match_legacy_constants(self) -> None:
        assert SHORTS_ASPECT_DIMENSIONS[SHORTS_DEFAULT_ASPECT] == (SHORTS_WIDTH, SHORTS_HEIGHT)


class TestShortsMusicVolume:
    def test_default_matches_ducking_module_baseline(self) -> None:
        from docu_studio.common.audio_ducking import MUSIC_BASELINE_DB

        cfg = ShortsConfig(topic="x")
        assert cfg.music_volume_db == SHORTS_DEFAULT_MUSIC_VOLUME_DB == MUSIC_BASELINE_DB

    def test_accepts_min_and_max_bounds(self) -> None:
        ShortsConfig(topic="x", music_volume_db=SHORTS_MUSIC_VOLUME_MIN_DB)
        ShortsConfig(topic="x", music_volume_db=SHORTS_MUSIC_VOLUME_MAX_DB)

    def test_rejects_below_minimum(self) -> None:
        with pytest.raises(ValueError, match="music_volume_db"):
            ShortsConfig(topic="x", music_volume_db=SHORTS_MUSIC_VOLUME_MIN_DB - 1)

    def test_rejects_above_maximum(self) -> None:
        with pytest.raises(ValueError, match="music_volume_db"):
            ShortsConfig(topic="x", music_volume_db=SHORTS_MUSIC_VOLUME_MAX_DB + 1)
