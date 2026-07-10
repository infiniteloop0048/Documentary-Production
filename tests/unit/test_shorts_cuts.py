"""Unit tests for plan_cuts — pure, seeded segment timing for shorts assembly."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_cuts import (
    MAX_SEGMENT_DURATION,
    MIN_SEGMENT_DELTA,
    MIN_SEGMENT_DURATION,
    choose_crop_strategy,
    plan_cuts,
    plan_cuts_window,
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


class TestChooseCropStrategy:
    def test_standard_16_9_uses_center_crop(self) -> None:
        assert choose_crop_strategy(1920, 1080) == "center_crop"

    def test_already_vertical_source_uses_center_crop(self) -> None:
        assert choose_crop_strategy(1080, 1920) == "center_crop"

    def test_square_source_uses_center_crop(self) -> None:
        assert choose_crop_strategy(1080, 1080) == "center_crop"

    def test_moderately_wide_21_9_uses_center_crop(self) -> None:
        assert choose_crop_strategy(2560, 1080) == "center_crop"

    def test_ultra_wide_32_9_uses_blur_pad(self) -> None:
        assert choose_crop_strategy(3840, 1080) == "blur_pad"

    def test_rejects_non_positive_dimensions(self) -> None:
        with pytest.raises(ValueError):
            choose_crop_strategy(0, 1080)
        with pytest.raises(ValueError):
            choose_crop_strategy(1920, 0)


class TestPlanCutsBeatSnapping:
    def test_snaps_interior_cut_to_nearest_beat_within_tolerance(self) -> None:
        # seed=1 at 30s/8clips produces a first interior boundary somewhere
        # in [MIN_SEGMENT_DURATION, MAX_SEGMENT_DURATION]; place a beat 0.2s
        # away from it and confirm the boundary moves onto that beat exactly.
        baseline = plan_cuts(total_duration=30.0, n_clips=8, seed=1)
        first_boundary = baseline[1].start
        beat = round(first_boundary + 0.2, 2)
        grid = [beat]

        snapped = plan_cuts(total_duration=30.0, n_clips=8, seed=1, beat_grid=grid)
        assert snapped[1].start == beat

    def test_does_not_snap_beyond_tolerance(self) -> None:
        baseline = plan_cuts(total_duration=30.0, n_clips=8, seed=1)
        first_boundary = baseline[1].start
        far_beat = round(first_boundary + 1.0, 2)  # outside +/-0.4s

        snapped = plan_cuts(total_duration=30.0, n_clips=8, seed=1, beat_grid=[far_beat])
        assert snapped[1].start == first_boundary

    def test_never_snaps_two_cuts_to_the_same_beat(self) -> None:
        # plan_cuts' own MIN_SEGMENT_DURATION (2.0s) means two real interior
        # boundaries can never both land within +/-0.4s of one beat, so this
        # exercises the used-beats guard directly on the private helper with
        # a synthetic, deliberately-close pair of boundaries instead.
        from docu_studio.shorts.shorts_cuts import _snap_boundaries_to_beats

        boundaries = [0.0, 5.0, 5.3, 10.0]
        grid = [5.15]  # within 0.4s of both 5.0 and 5.3

        snapped, count = _snap_boundaries_to_beats(boundaries, grid)
        assert count <= 1
        assert snapped.count(5.15) <= 1

    def test_total_duration_preserved_after_snapping(self) -> None:
        baseline = plan_cuts(total_duration=47.3, n_clips=10, seed=7)
        grid = [round(s.start + 0.1, 2) for s in baseline[1:]]

        snapped = plan_cuts(total_duration=47.3, n_clips=10, seed=7, beat_grid=grid)
        assert snapped[-1].start + snapped[-1].duration == pytest.approx(47.3, abs=0.02)
        assert sum(s.duration for s in snapped) == pytest.approx(47.3, abs=0.02)

    def test_no_beat_grid_matches_original_unsnapped_output(self) -> None:
        a = plan_cuts(total_duration=33.0, n_clips=9, seed=99)
        b = plan_cuts(total_duration=33.0, n_clips=9, seed=99, beat_grid=None)
        assert a == b

    def test_matches_frozen_ground_truth_from_pre_task4_implementation(self) -> None:
        # Regression guard: these exact (start, duration) pairs were captured by running
        # the pre-Task-4 plan_cuts (git commit 9438ea2f6d4ba5f2dca37a89187fe9d45e9252d7,
        # before beat_grid/loop_revisit existed) on total_duration=30.0, n_clips=8, seed=1.
        # Durations are asserted with exact equality (not pytest.approx) — Task 4's
        # boundary-subtraction reconstruction (`boundaries[i+1] - boundaries[i]`) silently
        # drifted every interior duration at the ULP level (e.g. 2.84 became
        # 2.8399999999999994), and pytest.approx would not have caught that. If this test
        # ever starts comparing new-code-against-new-code instead of against these frozen
        # literals, it stops being a real regression guard.
        expected = [
            (0, 0.0, 2.27, 0),
            (1, 2.27, 3.69, 1),
            (2, 5.96, 2.51, 2),
            (3, 8.469999999999999, 3.3, 3),
            (4, 11.77, 2.19, 4),
            (5, 13.959999999999999, 3.67, 5),
            (6, 17.63, 2.87, 6),
            (7, 20.5, 3.52, 7),
            (8, 24.02, 2.0, 0),
            (9, 26.02, 3.9800000000000004, 1),
        ]

        segments = plan_cuts(total_duration=30.0, n_clips=8, seed=1)

        assert len(segments) == len(expected)
        for seg, (index, start, duration, clip_index) in zip(segments, expected):
            assert seg.index == index
            assert seg.start == start
            assert seg.duration == duration
            assert seg.clip_index == clip_index


class TestPlanCutsLoopRevisit:
    def test_reserves_final_segment_for_clip_zero(self) -> None:
        segments = plan_cuts(total_duration=30.0, n_clips=8, seed=1, loop_revisit=True)
        last = segments[-1]
        assert last.loop_revisit is True
        assert last.clip_index == 0

    def test_revisit_duration_within_spec_band(self) -> None:
        segments = plan_cuts(total_duration=30.0, n_clips=8, seed=1, loop_revisit=True)
        last = segments[-1]
        assert 1.5 <= last.duration <= 2.0

    def test_revisit_ends_exactly_on_total_duration(self) -> None:
        segments = plan_cuts(total_duration=41.7, n_clips=6, seed=4, loop_revisit=True)
        last = segments[-1]
        assert last.start + last.duration == pytest.approx(41.7, abs=0.02)

    def test_total_duration_preserved_with_revisit(self) -> None:
        segments = plan_cuts(total_duration=41.7, n_clips=6, seed=4, loop_revisit=True)
        assert sum(s.duration for s in segments) == pytest.approx(41.7, abs=0.02)

    def test_non_revisit_segments_are_not_flagged(self) -> None:
        segments = plan_cuts(total_duration=30.0, n_clips=8, seed=1, loop_revisit=True)
        assert all(not s.loop_revisit for s in segments[:-1])

    def test_skipped_entirely_when_total_duration_too_short(self) -> None:
        segments = plan_cuts(total_duration=5.0, n_clips=2, seed=1, loop_revisit=True)
        assert all(not s.loop_revisit for s in segments)

    def test_disabled_by_default_matches_original_output(self) -> None:
        a = plan_cuts(total_duration=33.0, n_clips=9, seed=99)
        b = plan_cuts(total_duration=33.0, n_clips=9, seed=99, loop_revisit=False)
        assert a == b

    def test_beat_grid_also_snaps_the_revisit_cut_point(self) -> None:
        baseline = plan_cuts(total_duration=30.0, n_clips=8, seed=1, loop_revisit=True)
        revisit_start = baseline[-1].start
        beat = round(revisit_start + 0.15, 2)

        snapped = plan_cuts(
            total_duration=30.0, n_clips=8, seed=1, loop_revisit=True, beat_grid=[beat],
        )
        assert snapped[-1].start == beat
        assert snapped[-1].loop_revisit is True
        assert sum(s.duration for s in snapped) == pytest.approx(30.0, abs=0.02)


class TestPlanCutsWindow:
    def test_all_segments_stay_within_the_window_bounds(self) -> None:
        segments = plan_cuts_window(window_start=10.0, window_duration=9.0, n_clips=4, seed=1)
        assert segments[0].start == pytest.approx(10.0)
        assert segments[-1].start + segments[-1].duration == pytest.approx(19.0, abs=0.02)
        for seg in segments:
            assert seg.start >= 10.0 - 1e-9
            assert seg.start + seg.duration <= 19.0 + 1e-9

    def test_segments_sum_to_exact_window_duration(self) -> None:
        segments = plan_cuts_window(window_start=5.0, window_duration=12.0, n_clips=5, seed=3)
        assert sum(s.duration for s in segments) == pytest.approx(12.0, abs=0.02)

    def test_non_final_segments_respect_min_max_bounds(self) -> None:
        segments = plan_cuts_window(window_start=0.0, window_duration=20.0, n_clips=6, seed=7)
        for seg in segments[:-1]:
            assert MIN_SEGMENT_DURATION <= seg.duration <= MAX_SEGMENT_DURATION

    def test_short_window_returns_single_segment(self) -> None:
        segments = plan_cuts_window(window_start=3.0, window_duration=1.8, n_clips=1, seed=1)
        assert len(segments) == 1
        assert segments[0].start == pytest.approx(3.0)
        assert segments[0].duration == pytest.approx(1.8)

    def test_rejects_non_positive_window_duration(self) -> None:
        with pytest.raises(ValueError):
            plan_cuts_window(window_start=0.0, window_duration=0.0, n_clips=1, seed=1)

    def test_rejects_non_positive_n_clips(self) -> None:
        with pytest.raises(ValueError):
            plan_cuts_window(window_start=0.0, window_duration=10.0, n_clips=0, seed=1)

    def test_reproducible_by_seed(self) -> None:
        a = plan_cuts_window(window_start=0.0, window_duration=15.0, n_clips=4, seed=9)
        b = plan_cuts_window(window_start=0.0, window_duration=15.0, n_clips=4, seed=9)
        assert a == b

    def test_beat_within_window_and_tolerance_is_snapped(self) -> None:
        baseline = plan_cuts_window(window_start=10.0, window_duration=12.0, n_clips=4, seed=2)
        first_interior = baseline[1].start
        beat = round(first_interior + 0.2, 2)

        snapped = plan_cuts_window(
            window_start=10.0, window_duration=12.0, n_clips=4, seed=2, beat_grid=[beat],
        )
        assert snapped[1].start == beat


class TestBeatsWithinWindow:
    def test_keeps_beats_inside_the_window(self) -> None:
        from docu_studio.shorts.shorts_cuts import _beats_within_window
        result = _beats_within_window([5.0, 12.0, 18.0], window_start=10.0, window_end=20.0)
        assert result == [12.0, 18.0]

    def test_drops_beats_outside_the_window(self) -> None:
        from docu_studio.shorts.shorts_cuts import _beats_within_window
        result = _beats_within_window([1.0, 9.9, 20.1, 30.0], window_start=10.0, window_end=20.0)
        assert result == []

    def test_keeps_beats_exactly_on_the_window_edges(self) -> None:
        from docu_studio.shorts.shorts_cuts import _beats_within_window
        result = _beats_within_window([10.0, 20.0], window_start=10.0, window_end=20.0)
        assert result == [10.0, 20.0]

    def test_a_beat_belonging_to_a_neighboring_sentences_span_is_excluded(self) -> None:
        # Two adjacent windows sharing one global beat_grid: a beat that sits
        # just past this window's own end (i.e. inside the *next* sentence's
        # span) must never be considered for snapping in this window, even
        # though it would be well within BEAT_SNAP_TOLERANCE of this
        # window's own end boundary.
        from docu_studio.shorts.shorts_cuts import BEAT_SNAP_TOLERANCE, _beats_within_window
        neighbor_beat = 20.0 + (BEAT_SNAP_TOLERANCE / 2)
        result = _beats_within_window([neighbor_beat], window_start=10.0, window_end=20.0)
        assert result == []
