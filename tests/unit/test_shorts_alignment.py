"""Unit tests for the pure Whisper-to-script word alignment matcher."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_alignment import align_words_to_script


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

    def test_leading_unmatched_run_collapses_to_first_match_start(self) -> None:
        script_words = ["um", "so", "hello"]
        whisper_words = [("hello", 1.0, 1.5)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1 / 3)
        assert timings[0].start == pytest.approx(1.0)
        assert timings[0].end == pytest.approx(1.0)
        assert timings[1].start == pytest.approx(1.0)
        assert timings[2].start == pytest.approx(1.0)
        assert timings[2].end == pytest.approx(1.5)

    def test_trailing_unmatched_run_collapses_to_last_match_end(self) -> None:
        script_words = ["hello", "there", "friend"]
        whisper_words = [("hello", 0.0, 0.5)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1 / 3)
        assert timings[-1].start == pytest.approx(0.5)
        assert timings[-1].end == pytest.approx(0.5)

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
