"""Unit tests for Ken Burns direction selection."""
from __future__ import annotations

from docu_studio.slideshow.slideshow_motion import direction_for_index


class TestDirectionForIndex:
    def test_even_indices_zoom_in(self) -> None:
        assert direction_for_index(0) == "in"
        assert direction_for_index(2) == "in"

    def test_odd_indices_zoom_out(self) -> None:
        assert direction_for_index(1) == "out"
        assert direction_for_index(3) == "out"

    def test_alternates_across_a_run(self) -> None:
        assert [direction_for_index(i) for i in range(5)] == ["in", "out", "in", "out", "in"]
