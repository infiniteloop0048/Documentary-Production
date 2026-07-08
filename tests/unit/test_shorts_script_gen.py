"""Unit tests for shorts script-generation helpers: word-target math and
sentence splitting."""
from __future__ import annotations

from docu_studio.shorts.shorts_script_gen import split_sentences, target_word_count


class TestTargetWordCount:
    def test_thirty_seconds_at_170_wpm(self) -> None:
        assert target_word_count(30) == round(30 / 60 * 170)  # 85

    def test_fifteen_seconds_minimum(self) -> None:
        assert target_word_count(15) == round(15 / 60 * 170)  # 42 or 43

    def test_sixty_seconds_maximum(self) -> None:
        assert target_word_count(60) == 170

    def test_scales_linearly_with_duration(self) -> None:
        assert target_word_count(60) == target_word_count(30) * 2 or \
            abs(target_word_count(60) - target_word_count(30) * 2) <= 1


class TestSplitSentences:
    def test_splits_on_terminal_punctuation(self) -> None:
        text = "This is one. This is two! Is this three?"
        assert split_sentences(text) == [
            "This is one.", "This is two!", "Is this three?",
        ]

    def test_collapses_internal_whitespace(self) -> None:
        text = "Hello   world.\nSecond   line."
        result = split_sentences(text)
        assert result == ["Hello world.", "Second line."]

    def test_empty_text_returns_empty_list(self) -> None:
        assert split_sentences("") == []
        assert split_sentences("   ") == []

    def test_single_sentence_no_trailing_punctuation(self) -> None:
        assert split_sentences("just one clause") == ["just one clause"]
