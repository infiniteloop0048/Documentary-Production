"""Unit tests for Slideshow's LLM narration generation: word-count math and
prompt construction against a mocked LLMProvider."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docu_studio.slideshow.slideshow_script_gen import (
    generate_slideshow_script,
    target_word_count,
)


class TestTargetWordCount:
    def test_default_pace_and_seconds_per_image(self) -> None:
        # 8 images * 5.0s/image = 40s; 40/60 * 150 wpm = 100 words
        assert target_word_count(8) == 100

    def test_custom_seconds_per_image(self) -> None:
        # 6 images * 10.0s/image = 60s; 60/60 * 150 wpm = 150 words
        assert target_word_count(6, seconds_per_image=10.0) == 150

    def test_custom_wpm(self) -> None:
        # 6 images * 10.0s/image = 60s; 60/60 * 120 wpm = 120 words
        assert target_word_count(6, seconds_per_image=10.0, wpm=120) == 120

    def test_zero_image_count_raises(self) -> None:
        with pytest.raises(ValueError):
            target_word_count(0)

    def test_negative_image_count_raises(self) -> None:
        with pytest.raises(ValueError):
            target_word_count(-1)


class TestGenerateSlideshowScript:
    def test_calls_llm_with_target_words_and_topic_prompt(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "  Some narration text.  "

        result = generate_slideshow_script("Mountain landscapes", 8, llm)

        assert result == "Some narration text."
        llm.generate_script.assert_called_once()
        _, kwargs = llm.generate_script.call_args
        assert kwargs["target_words"] == 100
        assert "Mountain landscapes" in kwargs["topic"]

    def test_prompt_requests_even_descriptive_style_not_hook_payoff(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "text"

        generate_slideshow_script("Topic", 6, llm)

        _, kwargs = llm.generate_script.call_args
        prompt = kwargs["topic"]
        assert "descriptive" in prompt.lower()
        assert "no cold-open hook" in prompt.lower()
        assert "no payoff" in prompt.lower()
