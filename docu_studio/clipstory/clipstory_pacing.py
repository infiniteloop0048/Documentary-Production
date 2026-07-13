"""Pure duration-fit math for Clip Story — no I/O, no ffmpeg calls. Layers 2-3 of
the three-layer duration-fit algorithm (Layer 1 word-count targeting lives in
clipstory_script_gen.py): Layer 2 is the bounded atempo speed factor
(evaluate_fit), Layer 3 is the halt decision (FitResult.should_halt) computed on
the residual AFTER the clamped tempo is applied — not the same question as
"did we have to clamp at all", which is why should_halt is not folded into
clamp_speed_factor's return value.

A separate concern, plan_reconciliation, handles the small remaining gap left
even when Layer 2 succeeds (should_halt is False): ffmpeg's -shortest mux flag
is only safe to truncate the LONGER stream, so if the tempo-adjusted narration
comes out shorter than the trimmed video, it must be padded with silence rather
than left to -shortest (which would wrongly truncate the video instead).
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LO_SPEED_FACTOR = 0.85
DEFAULT_HI_SPEED_FACTOR = 1.15
DEFAULT_HALT_TOLERANCE = 0.10
DEFAULT_RECONCILE_EPSILON = 0.05


def compute_ideal_speed_factor(actual_duration: float, target_duration: float) -> float:
    """Return the atempo factor that would land *actual_duration* exactly on
    *target_duration* (ffmpeg atempo semantics: resulting = input / tempo)."""
    if target_duration <= 0:
        raise ValueError("target_duration must be positive")
    if actual_duration <= 0:
        raise ValueError("actual_duration must be positive")
    return actual_duration / target_duration


def clamp_speed_factor(
    ideal_factor: float,
    lo: float = DEFAULT_LO_SPEED_FACTOR,
    hi: float = DEFAULT_HI_SPEED_FACTOR,
) -> float:
    return max(lo, min(hi, ideal_factor))


@dataclass(frozen=True)
class FitResult:
    ideal_factor: float
    applied_factor: float
    resulting_duration: float
    residual_ratio: float
    should_halt: bool


def evaluate_fit(
    actual_duration: float,
    target_duration: float,
    lo: float = DEFAULT_LO_SPEED_FACTOR,
    hi: float = DEFAULT_HI_SPEED_FACTOR,
    halt_tolerance: float = DEFAULT_HALT_TOLERANCE,
) -> FitResult:
    ideal_factor = compute_ideal_speed_factor(actual_duration, target_duration)
    applied_factor = clamp_speed_factor(ideal_factor, lo, hi)
    resulting_duration = actual_duration / applied_factor
    residual_ratio = abs(resulting_duration - target_duration) / target_duration
    should_halt = residual_ratio > halt_tolerance
    return FitResult(
        ideal_factor=ideal_factor,
        applied_factor=applied_factor,
        resulting_duration=resulting_duration,
        residual_ratio=residual_ratio,
        should_halt=should_halt,
    )


@dataclass(frozen=True)
class ReconciliationPlan:
    action: str  # "pad" | "trim_fade" | "none"
    adjustment_seconds: float


def plan_reconciliation(
    actual_duration: float,
    target_duration: float,
    epsilon: float = DEFAULT_RECONCILE_EPSILON,
) -> ReconciliationPlan:
    diff = target_duration - actual_duration
    if diff > epsilon:
        return ReconciliationPlan(action="pad", adjustment_seconds=diff)
    if diff < -epsilon:
        return ReconciliationPlan(action="trim_fade", adjustment_seconds=-diff)
    return ReconciliationPlan(action="none", adjustment_seconds=0.0)
