"""Unit tests for the pure Whisper-to-script word alignment matcher."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_alignment import (
    _MIN_INTERP_WORD_SPAN,
    _interpolate,
    align_words_to_script,
)


class TestAlignWordsToScript:
    def test_perfect_match_uses_whisper_timings_directly(self) -> None:
        script_words = ["the", "cat", "sat", "down"]
        whisper_words = [("the", 0.0, 0.3), ("cat", 0.3, 0.6), ("sat", 0.6, 0.9), ("down", 0.9, 1.2)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1.0)
        assert [t.word for t in timings] == script_words
        assert [(t.start, t.end) for t in timings] == [(0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.2)]

    def test_missing_middle_word_is_interpolated(self) -> None:
        script_words = ["the", "quick", "cat", "sat"]
        # whisper dropped "quick" entirely
        whisper_words = [("the", 0.0, 0.3), ("cat", 0.6, 0.9), ("sat", 0.9, 1.2)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(0.75)
        assert timings[0].word == "the"
        assert (timings[0].start, timings[0].end) == (0.0, 0.3)
        # "quick" interpolated between "the".end (0.3) and "cat".start (0.6)
        assert timings[1].word == "quick"
        assert timings[1].start == pytest.approx(0.3)
        assert timings[1].end == pytest.approx(0.6)
        assert (timings[2].start, timings[2].end) == (0.6, 0.9)
        assert (timings[3].start, timings[3].end) == (0.9, 1.2)

    def test_mismatched_misheard_word_is_interpolated(self) -> None:
        script_words = ["the", "cat", "sat"]
        # whisper misheard "cat" as "bat"
        whisper_words = [("the", 0.0, 0.3), ("bat", 0.3, 0.6), ("sat", 0.6, 0.9)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(2 / 3)
        assert timings[1].word == "cat"
        # interpolated between "the".end (0.3) and "sat".start (0.6)
        assert timings[1].start == pytest.approx(0.3)
        assert timings[1].end == pytest.approx(0.6)

    def test_leading_unmatched_run_backfills_from_first_match_start(self) -> None:
        script_words = ["um", "so", "hello"]
        whisper_words = [("hello", 1.0, 1.5)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1 / 3)
        # 2 unmatched words, min span 0.05 each -> back-filled from 1.0 - 0.1 = 0.9,
        # strictly increasing, no duplicate timestamps.
        assert timings[0].start == pytest.approx(0.9)
        assert timings[0].end == pytest.approx(0.95)
        assert timings[1].start == pytest.approx(0.95)
        assert timings[1].end == pytest.approx(1.0)
        assert timings[2].start == pytest.approx(1.0)
        assert timings[2].end == pytest.approx(1.5)

    def test_trailing_unmatched_run_forward_fills_from_last_match_end(self) -> None:
        script_words = ["hello", "there", "friend"]
        whisper_words = [("hello", 0.0, 0.5)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1 / 3)
        # 2 unmatched words, min span 0.05 each -> forward-filled from 0.5,
        # strictly increasing, no duplicate/zero-duration timestamps.
        assert timings[1].start == pytest.approx(0.5)
        assert timings[1].end == pytest.approx(0.55)
        assert timings[2].start == pytest.approx(0.55)
        assert timings[2].end == pytest.approx(0.6)

    def test_empty_script_returns_empty_and_zero_fraction(self) -> None:
        timings, fraction = align_words_to_script([], [("hello", 0.0, 0.5)])
        assert timings == []
        assert fraction == 0.0

    def test_no_matches_at_all_returns_zero_duration_timeline(self) -> None:
        script_words = ["alpha", "beta"]
        whisper_words = [("gamma", 0.0, 0.3), ("delta", 0.3, 0.6)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == 0.0
        assert all(t.start == 0.0 and t.end == 0.0 for t in timings)

    def test_repeated_words_align_positionally_not_all_to_first_occurrence(self) -> None:
        script_words = ["go", "go", "go"]
        whisper_words = [("go", 0.0, 0.2), ("go", 0.2, 0.4), ("go", 0.4, 0.6)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1.0)
        assert [(t.start, t.end) for t in timings] == [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6)]


def _no_duplicate_or_decreasing_starts(timings) -> bool:
    starts = [t.start for t in timings]
    return all(b > a for a, b in zip(starts, starts[1:]))


class TestInterpolateDirect:
    """Direct tests of _interpolate() covering leading-run, trailing-run, and
    middle-run collapse — the 3 shapes that previously produced identical/
    zero-duration timestamps and, downstream, overlapping ASS caption cues."""

    def test_leading_run_backfills_with_strictly_increasing_spans(self) -> None:
        script_words = ["a", "b", "c", "d"]
        matched = [None, None, None, (0.2, 0.4)]
        result = _interpolate(script_words, matched)
        assert _no_duplicate_or_decreasing_starts(result)
        assert result[0].start == pytest.approx(0.2 - 3 * _MIN_INTERP_WORD_SPAN)
        assert result[2].end == pytest.approx(0.2)
        assert result[3].start == pytest.approx(0.2)

    def test_trailing_run_forward_fills_with_strictly_increasing_spans(self) -> None:
        script_words = ["a", "b", "c", "d"]
        matched = [(0.0, 0.2), None, None, None]
        result = _interpolate(script_words, matched)
        assert _no_duplicate_or_decreasing_starts(result)
        assert result[1].start == pytest.approx(0.2)
        assert result[-1].end == pytest.approx(0.2 + 3 * _MIN_INTERP_WORD_SPAN)

    def test_middle_run_with_misordered_neighbors_still_gets_positive_span(self) -> None:
        """left.end (0.5) >= right.start (0.3) — a genuinely misordered Whisper
        match. The interpolated word can't satisfy both anchors at once, but it
        must still get a real positive span anchored to left.end rather than
        collapsing to a single identical/zero-duration timestamp."""
        script_words = ["a", "b", "c"]
        matched = [(0.0, 0.5), None, (0.3, 0.6)]
        result = _interpolate(script_words, matched)
        assert result[1].start == pytest.approx(0.5)
        assert result[1].end == pytest.approx(0.5 + _MIN_INTERP_WORD_SPAN)
        assert result[1].end > result[1].start

    def test_middle_run_with_too_tight_positive_span_is_widened(self) -> None:
        """left.end (0.2) < right.start (0.21) but the raw span (0.01s) is far
        too small to hold 2 readable words — must be widened to the minimum
        rather than producing two near-duplicate timestamps."""
        script_words = ["a", "b", "c", "d"]
        matched = [(0.0, 0.2), None, None, (0.21, 0.4)]
        result = _interpolate(script_words, matched)
        assert _no_duplicate_or_decreasing_starts(result[:3])
        assert result[1].end - result[1].start == pytest.approx(_MIN_INTERP_WORD_SPAN)
        assert result[2].end - result[2].start == pytest.approx(_MIN_INTERP_WORD_SPAN)

    def test_reproduces_climate_change_seven_cue_chain_as_readable_spans(self) -> None:
        """Regression case mirroring the real Climate_Change_20260711_014823
        capture: 7 consecutive unmatched words squeezed between neighbors only
        0.05s apart (21.94 -> 21.99), previously collapsing to a single
        identical timestamp for all 7. Each word must now get its own
        strictly increasing, minimum-readable span."""
        script_words = ["w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8"]
        matched = [(0.0, 21.94), None, None, None, None, None, None, None, (21.99, 22.5)]
        result = _interpolate(script_words, matched)
        interpolated = result[1:8]
        assert _no_duplicate_or_decreasing_starts(interpolated)
        for word in interpolated:
            assert word.end - word.start == pytest.approx(_MIN_INTERP_WORD_SPAN)
        assert interpolated[0].start == pytest.approx(21.94)
