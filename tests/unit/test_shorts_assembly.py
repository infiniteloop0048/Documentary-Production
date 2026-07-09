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
    _insert_punch_card,
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


def _plain_segments(*durations: float) -> list[Segment]:
    segs = []
    start = 0.0
    for i, d in enumerate(durations):
        segs.append(Segment(index=i, start=start, duration=d, clip_index=i))
        start += d
    return segs


class TestInsertPunchCard:
    def test_shrinks_adjacent_segment_and_preserves_total_duration(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        total_before = sum(s.duration for s in segments)

        new_segments, window = _insert_punch_card(
            segments, punch=(1, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )

        assert window is not None
        assert sum(s.duration for s in new_segments) == pytest.approx(total_before)

    def test_card_segment_is_flagged_and_carries_text(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(1, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )
        punch_segs = [s for s in new_segments if s.is_punch]
        assert len(punch_segs) == 1
        assert punch_segs[0].punch_text == "90 PERCENT"
        assert punch_segs[0].duration == pytest.approx(window[1] - window[0])

    def test_card_placed_before_target_when_not_the_first_segment(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(1, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )
        card_index = next(i for i, s in enumerate(new_segments) if s.is_punch)
        # the shrunk original target must immediately follow the card
        assert not new_segments[card_index + 1].is_punch
        assert new_segments[card_index + 1].start == pytest.approx(window[1])

    def test_card_steals_from_the_end_when_target_is_first_segment(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )
        assert window is not None
        assert window[0] > 0.0  # card doesn't start at t=0
        first = new_segments[0]
        assert not first.is_punch
        assert first.start == 0.0

    def test_returns_unchanged_when_no_footage_segments(self) -> None:
        segments = [Segment(index=0, start=28.0, duration=1.75, clip_index=0, loop_revisit=True)]
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[0.0],
        )
        assert window is None
        assert new_segments == segments

    def test_skips_gracefully_when_target_segment_too_short_to_steal_from(self) -> None:
        segments = _plain_segments(0.4, 3.0)  # first segment too short for a 1.0s card
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[0.0, 0.4],
        )
        assert window is None
        assert new_segments == segments

    def test_sentence_index_out_of_range_returns_unchanged(self) -> None:
        segments = _plain_segments(3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(5, "90 PERCENT"), sentence_starts=[0.0, 3.0],
        )
        assert window is None
        assert new_segments == segments

    def test_loop_revisit_segment_is_never_chosen_as_the_target(self) -> None:
        segments = [
            Segment(index=0, start=0.0, duration=3.0, clip_index=0),
            Segment(index=1, start=3.0, duration=1.75, clip_index=0, loop_revisit=True),
        ]
        # sentence start lands exactly on the revisit segment's start
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[3.0],
        )
        assert window is not None
        assert window[1] <= 3.0  # card placed within the non-revisit segment only
