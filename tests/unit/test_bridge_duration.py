"""Unit tests for Bridge's (minutes, seconds) -> precise-minutes duration conversion."""
from __future__ import annotations

import pytest

from docu_studio.gui.bridge import duration_to_minutes


class TestDurationToMinutes:
    def test_whole_minutes_no_seconds(self) -> None:
        assert duration_to_minutes(5, 0) == 5.0

    def test_minutes_and_seconds_combine_fractionally(self) -> None:
        assert duration_to_minutes(12, 30) == pytest.approx(12.5)

    def test_seconds_only(self) -> None:
        assert duration_to_minutes(0, 30) == pytest.approx(0.5)

    def test_zero_duration_raises(self) -> None:
        with pytest.raises(ValueError):
            duration_to_minutes(0, 0)

    def test_negative_total_raises(self) -> None:
        with pytest.raises(ValueError):
            duration_to_minutes(-1, 0)
