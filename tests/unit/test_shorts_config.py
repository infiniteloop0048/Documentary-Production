"""Unit tests for ShortsConfig bounds validation."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_config import (
    SHORTS_DEFAULT_DURATION,
    SHORTS_HEIGHT,
    SHORTS_MAX_DURATION,
    SHORTS_MIN_DURATION,
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
