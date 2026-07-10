"""Unit tests for sentence_spans — pure sentence-level [start,end] derivation
from word timestamps, used to scope footage cutting to the narrating sentence."""
from __future__ import annotations

import pytest

from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_sentence_spans import sentence_spans


def _wt(word: str, start: float, end: float) -> WordTiming:
    return WordTiming(word=word, start=start, end=end)


class TestSentenceSpans:
    def test_two_sentences_tile_the_full_duration_with_a_gap_between(self) -> None:
        sentences = ["Hello world.", "Goodbye now."]
        timestamps = [
            _wt("Hello", 0.0, 0.4), _wt("world.", 0.4, 0.9),
            _wt("Goodbye", 1.3, 1.8), _wt("now.", 1.8, 2.2),
        ]
        spans = sentence_spans(sentences, timestamps, total_duration=2.5)
        assert spans == [(0.0, 1.3), (1.3, 2.5)]

    def test_spans_are_contiguous_and_sum_to_total_duration(self) -> None:
        sentences = ["One two three.", "Four five.", "Six."]
        timestamps = [
            _wt("One", 0.0, 0.3), _wt("two", 0.3, 0.6), _wt("three.", 0.6, 1.0),
            _wt("Four", 1.0, 1.3), _wt("five.", 1.3, 1.6),
            _wt("Six.", 1.7, 2.0),
        ]
        spans = sentence_spans(sentences, timestamps, total_duration=2.4)
        assert spans[0][1] == spans[1][0]
        assert spans[1][1] == spans[2][0]
        assert spans[0][0] == 0.0
        assert spans[-1][1] == 2.4
        assert sum(e - s for s, e in spans) == pytest.approx(2.4)

    def test_tier3_estimated_style_contiguous_timestamps_produce_zero_gap_spans(self) -> None:
        # Tier 3 has no pauses at all — words are packed with zero gap, so each
        # sentence's raw end already equals the next sentence's raw start.
        sentences = ["Hi there.", "Bye."]
        timestamps = [
            _wt("Hi", 0.0, 0.3), _wt("there.", 0.3, 0.7),
            _wt("Bye.", 0.7, 1.0),
        ]
        spans = sentence_spans(sentences, timestamps, total_duration=1.0)
        assert spans == [(0.0, 0.7), (0.7, 1.0)]

    def test_fewer_timestamps_than_needed_collapses_trailing_sentence_to_zero_length(self) -> None:
        sentences = ["Word one two.", "Missing entirely here."]
        timestamps = [_wt("Word", 0.0, 0.3), _wt("one", 0.3, 0.6), _wt("two.", 0.6, 1.0)]
        spans = sentence_spans(sentences, timestamps, total_duration=1.0)
        assert spans[0] == (0.0, 1.0)
        assert spans[1] == (1.0, 1.0)

    def test_single_sentence_spans_the_entire_duration(self) -> None:
        sentences = ["Only one sentence here."]
        timestamps = [
            _wt("Only", 0.0, 0.3), _wt("one", 0.3, 0.6),
            _wt("sentence", 0.6, 1.0), _wt("here.", 1.0, 1.4),
        ]
        spans = sentence_spans(sentences, timestamps, total_duration=1.6)
        assert spans == [(0.0, 1.6)]

    def test_empty_sentences_list_returns_empty(self) -> None:
        assert sentence_spans([], [], total_duration=10.0) == []

    def test_spans_are_monotonically_non_decreasing(self) -> None:
        sentences = ["A short one.", "Another.", "Last."]
        timestamps = [
            _wt("A", 0.0, 0.1), _wt("short", 0.1, 0.4), _wt("one.", 0.4, 0.7),
            _wt("Another.", 0.7, 1.2),
            _wt("Last.", 1.2, 1.5),
        ]
        spans = sentence_spans(sentences, timestamps, total_duration=1.5)
        for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
            assert s0 <= e0
            assert e0 <= s1
