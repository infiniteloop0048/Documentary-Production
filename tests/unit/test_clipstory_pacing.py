"""Unit tests for clipstory_pacing: pure duration-fit math, no I/O."""
from __future__ import annotations

import pytest

from docu_studio.clipstory.clipstory_pacing import (
    clamp_speed_factor,
    compute_ideal_speed_factor,
    evaluate_fit,
    plan_reconciliation,
)


class TestComputeIdealSpeedFactor:
    def test_normal_case(self) -> None:
        assert compute_ideal_speed_factor(actual_duration=15.0, target_duration=10.0) == pytest.approx(1.5)

    def test_actual_equals_target(self) -> None:
        assert compute_ideal_speed_factor(actual_duration=10.0, target_duration=10.0) == pytest.approx(1.0)

    def test_zero_target_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="target_duration"):
            compute_ideal_speed_factor(actual_duration=10.0, target_duration=0.0)

    def test_zero_actual_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="actual_duration"):
            compute_ideal_speed_factor(actual_duration=0.0, target_duration=10.0)


class TestClampSpeedFactor:
    def test_below_lower_bound_clamps_up(self) -> None:
        assert clamp_speed_factor(0.5) == 0.85

    def test_above_upper_bound_clamps_down(self) -> None:
        assert clamp_speed_factor(1.5) == 1.15

    def test_within_range_unchanged(self) -> None:
        assert clamp_speed_factor(1.0) == 1.0

    def test_exactly_at_lower_bound_unchanged(self) -> None:
        assert clamp_speed_factor(0.85) == 0.85

    def test_exactly_at_upper_bound_unchanged(self) -> None:
        assert clamp_speed_factor(1.15) == 1.15


class TestEvaluateFit:
    def test_within_bounds_no_halt_near_zero_residual(self) -> None:
        # ideal = 10.5/10.0 = 1.05, within [0.85, 1.15] -> applied == ideal,
        # resulting_duration == target exactly.
        fit = evaluate_fit(actual_duration=10.5, target_duration=10.0)
        assert fit.applied_factor == pytest.approx(fit.ideal_factor)
        assert fit.resulting_duration == pytest.approx(10.0)
        assert fit.residual_ratio == pytest.approx(0.0)
        assert fit.should_halt is False

    def test_clamped_small_residual_no_halt(self) -> None:
        # ideal = 12.0/10.0 = 1.2, clamped to 1.15 -> resulting = 12/1.15 = 10.4348
        fit = evaluate_fit(actual_duration=12.0, target_duration=10.0)
        assert fit.applied_factor == pytest.approx(1.15)
        assert fit.residual_ratio < 0.10
        assert fit.should_halt is False

    def test_clamped_large_residual_halts(self) -> None:
        # ideal = 20.0/10.0 = 2.0, clamped to 1.15 -> resulting = 20/1.15 = 17.39,
        # residual = 0.739 > 0.10
        fit = evaluate_fit(actual_duration=20.0, target_duration=10.0)
        assert fit.applied_factor == pytest.approx(1.15)
        assert fit.residual_ratio > 0.10
        assert fit.should_halt is True

    def test_residual_just_under_10_percent_does_not_halt(self) -> None:
        # target=100 keeps the 0.001 margin two orders of magnitude above float noise,
        # avoiding the false-boundary flip that an exact-0.10 literal construction hits
        # under IEEE-754 (12.65 / 1.15 does not land on exactly 11.0 in binary floats).
        # applied factor clamped to hi=1.15; actual chosen so resulting=109.9 (0.099 residual).
        fit = evaluate_fit(actual_duration=126.385, target_duration=100.0)
        assert fit.applied_factor == pytest.approx(1.15)
        assert fit.residual_ratio == pytest.approx(0.099)
        assert fit.should_halt is False

    def test_residual_just_over_10_percent_halts(self) -> None:
        # same construction, resulting=110.1 (0.101 residual) -> should_halt flips to True.
        fit = evaluate_fit(actual_duration=126.615, target_duration=100.0)
        assert fit.applied_factor == pytest.approx(1.15)
        assert fit.residual_ratio == pytest.approx(0.101)
        assert fit.should_halt is True


class TestPlanReconciliation:
    def test_shortfall_beyond_epsilon_pads(self) -> None:
        plan = plan_reconciliation(actual_duration=8.0, target_duration=10.0)
        assert plan.action == "pad"
        assert plan.adjustment_seconds == pytest.approx(2.0)

    def test_excess_beyond_epsilon_trims_with_fade(self) -> None:
        plan = plan_reconciliation(actual_duration=10.5, target_duration=10.0)
        assert plan.action == "trim_fade"
        assert plan.adjustment_seconds == pytest.approx(0.5)

    def test_within_epsilon_is_a_no_op(self) -> None:
        plan = plan_reconciliation(actual_duration=10.03, target_duration=10.0)
        assert plan.action == "none"
        assert plan.adjustment_seconds == pytest.approx(0.0)

    def test_just_under_epsilon_is_a_no_op(self) -> None:
        # diff=0.04 stays safely under epsilon=0.05 with margin far above float noise
        # (an exact diff==epsilon literal, e.g. 9.95 vs 10.0, is not reliable under
        # IEEE-754 since 10.0 - 9.95 does not land on exactly 0.05 in binary floats).
        plan = plan_reconciliation(actual_duration=9.96, target_duration=10.0, epsilon=0.05)
        assert plan.action == "none"
