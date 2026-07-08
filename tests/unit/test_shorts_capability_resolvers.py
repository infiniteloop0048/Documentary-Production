"""Unit tests for the Tier-3 estimated word-timing algorithm."""
from __future__ import annotations

import pytest

from docu_studio.shorts.capability_resolvers import WordTiming, estimate_word_timestamps


class TestEstimateWordTimestamps:
    def test_empty_script_returns_empty(self) -> None:
        assert estimate_word_timestamps("", 10.0) == []

    def test_zero_duration_returns_empty(self) -> None:
        assert estimate_word_timestamps("hello world", 0.0) == []

    def test_timestamps_span_the_full_duration(self) -> None:
        timestamps = estimate_word_timestamps("one two three four five", 10.0)
        assert timestamps[0].start == pytest.approx(0.0)
        assert timestamps[-1].end == pytest.approx(10.0, abs=1e-6)

    def test_timestamps_are_monotonically_increasing(self) -> None:
        timestamps = estimate_word_timestamps(
            "a short burst of narration with several words in it", 8.0
        )
        for a, b in zip(timestamps, timestamps[1:]):
            assert a.end == pytest.approx(b.start, abs=1e-9)
            assert b.start >= a.start

    def test_longer_words_get_more_time(self) -> None:
        timestamps = estimate_word_timestamps("a extraordinarily", 3.0)
        short_span = timestamps[0].end - timestamps[0].start
        long_span = timestamps[1].end - timestamps[1].start
        assert long_span > short_span

    def test_word_field_matches_input_order(self) -> None:
        timestamps = estimate_word_timestamps("red green blue", 3.0)
        assert [t.word for t in timestamps] == ["red", "green", "blue"]

    def test_returns_word_timing_instances(self) -> None:
        timestamps = estimate_word_timestamps("hi", 1.0)
        assert isinstance(timestamps[0], WordTiming)
