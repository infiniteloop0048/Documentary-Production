"""Unit tests for plan_cuts — pure, seeded segment timing for shorts assembly."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_cuts import (
    MAX_SEGMENT_DURATION,
    MIN_SEGMENT_DELTA,
    MIN_SEGMENT_DURATION,
    plan_cuts,
)


class TestPlanCuts:
    def test_segments_sum_to_exact_total_duration(self) -> None:
        segments = plan_cuts(total_duration=30.0, n_clips=8, seed=1)
        assert sum(s.duration for s in segments) == pytest.approx(30.0, abs=0.02)

    def test_last_segment_lands_exactly_on_audio_end(self) -> None:
        segments = plan_cuts(total_duration=47.3, n_clips=10, seed=7)
        assert segments[-1].start + segments[-1].duration == pytest.approx(47.3, abs=0.02)

    def test_non_final_segments_respect_min_max_bounds(self) -> None:
        segments = plan_cuts(total_duration=60.0, n_clips=15, seed=42)
        for seg in segments[:-1]:
            assert MIN_SEGMENT_DURATION <= seg.duration <= MAX_SEGMENT_DURATION

    def test_lengths_are_varied_not_uniform(self) -> None:
        segments = plan_cuts(total_duration=45.0, n_clips=12, seed=3)
        durations = [s.duration for s in segments]
        assert len(set(durations)) > 1

    def test_neighbors_differ_by_at_least_min_delta(self) -> None:
        segments = plan_cuts(total_duration=45.0, n_clips=12, seed=3)
        # exclude the pair ending at the trimmed final segment
        for a, b in zip(segments[:-2], segments[1:-1]):
            assert abs(b.duration - a.duration) >= MIN_SEGMENT_DELTA - 1e-9

    def test_same_seed_is_reproducible(self) -> None:
        a = plan_cuts(total_duration=33.0, n_clips=9, seed=99)
        b = plan_cuts(total_duration=33.0, n_clips=9, seed=99)
        assert a == b

    def test_different_seed_changes_the_plan(self) -> None:
        a = plan_cuts(total_duration=33.0, n_clips=9, seed=1)
        b = plan_cuts(total_duration=33.0, n_clips=9, seed=2)
        assert a != b

    def test_clip_index_cycles_within_n_clips(self) -> None:
        segments = plan_cuts(total_duration=60.0, n_clips=3, seed=5)
        assert all(0 <= s.clip_index < 3 for s in segments)

    def test_short_total_duration_returns_single_trimmed_segment(self) -> None:
        segments = plan_cuts(total_duration=1.5, n_clips=1, seed=1)
        assert len(segments) == 1
        assert segments[0].duration == pytest.approx(1.5)

    def test_rejects_non_positive_total_duration(self) -> None:
        with pytest.raises(ValueError):
            plan_cuts(total_duration=0.0, n_clips=1, seed=1)

    def test_rejects_non_positive_n_clips(self) -> None:
        with pytest.raises(ValueError):
            plan_cuts(total_duration=10.0, n_clips=0, seed=1)
