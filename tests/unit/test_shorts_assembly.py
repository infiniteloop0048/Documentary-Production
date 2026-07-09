"""Unit tests for shorts_assembly's pure-ish helper functions: _build_segment
(speed ramp + loop-revisit alternate window). ShortsFFmpeg is always a
MagicMock — no real ffmpeg calls.

Note: the plan's brief for this test file also references _insert_punch_card
(time-stealing math) — that helper is added in a later task and its import
will be added back to this file when it lands."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docu_studio.shorts.shorts_assembly import (
    SPEED_RAMP_FACTOR,
    _build_segment,
)
from docu_studio.shorts.shorts_cuts import Segment

_CLIP = {"path": "/clips/a.mp4", "width": 1920, "height": 1080}


def _ffmpeg(raw_duration: float, motion_start: float, method: str = "fallback") -> MagicMock:
    ffmpeg = MagicMock()
    ffmpeg.get_duration.return_value = raw_duration
    ffmpeg.detect_motion_window.return_value = (motion_start, method)
    return ffmpeg


class TestBuildSegmentSpeedRamp:
    def test_slow_fallback_long_clip_gets_sped_up_when_enabled(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=0.0, method="fallback")

        path, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 1
        ffmpeg.apply_speed_ramp.assert_called_once()

    def test_fast_motion_clip_not_sped_up(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=2.0, method="motion")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_short_source_clip_not_sped_up_even_if_fallback(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=10.0, motion_start=0.0, method="fallback")  # <15s

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_disabled_flag_never_speeds_up(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=0.0, method="fallback")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_source_window_is_cut_longer_by_the_speed_factor(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        trim_call = ffmpeg.trim_clip.call_args
        trimmed_duration = trim_call[0][2]
        assert trimmed_duration == pytest.approx(3.0 * SPEED_RAMP_FACTOR, abs=0.01)

    def test_ken_burns_duration_matches_plan_duration_when_sped(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        kb_call = ffmpeg.apply_ken_burns.call_args
        assert kb_call[0][2] == pytest.approx(3.0)  # duration arg == seg.duration exactly

    def test_cap_is_enforced_via_sped_count_and_max_param(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=2, max_sped_segments=2,  # already at cap
        )

        assert sped_count == 2
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_speed_factor_is_within_spec_band(self) -> None:
        assert 1.25 <= SPEED_RAMP_FACTOR <= 1.5


class TestBuildSegmentLoopRevisit:
    def test_loop_revisit_segment_never_sped_even_if_candidate(self, tmp_path: Path) -> None:
        seg = Segment(index=5, start=28.0, duration=1.75, clip_index=0, loop_revisit=True)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_picks_alternate_window_when_source_long_enough(self, tmp_path: Path) -> None:
        seg = Segment(index=5, start=28.0, duration=1.75, clip_index=0, loop_revisit=True)
        # motion detection would pick start=0.0 again, same as the (avoided) original
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="motion")

        _, _, window_start = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
            avoid_start=0.0,
        )

        assert window_start != 0.0
        assert window_start == pytest.approx(30.0 - 1.75)

    def test_falls_back_to_same_window_when_source_too_short(self, tmp_path: Path) -> None:
        seg = Segment(index=5, start=8.0, duration=1.75, clip_index=0, loop_revisit=True)
        # raw_duration - window = 2.0 - 1.75 = 0.25s < _LOOP_REVISIT_MIN_GAP -> no room to differ
        ffmpeg = _ffmpeg(raw_duration=2.0, motion_start=0.1, method="motion")

        _, _, window_start = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
            avoid_start=0.1,
        )

        assert window_start == 0.1

    def test_no_avoid_start_leaves_window_untouched(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=5.0, method="motion")

        _, _, window_start = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
        )

        assert window_start == 5.0
