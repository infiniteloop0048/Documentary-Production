"""Unit tests for clipstory_script_gen: Layer 1 word targeting + coordinated LLM call."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docu_studio.clipstory.clipstory_config import ClipSpec
from docu_studio.clipstory.clipstory_script_gen import (
    SegmentPlan,
    build_coordinated_prompt,
    count_words,
    estimated_seconds,
    generate_coordinated_narration,
    parse_coordinated_response,
    prepare_narration_review,
    target_word_count,
)


class TestTargetWordCount:
    def test_known_wpm_and_duration(self) -> None:
        assert target_word_count(duration_seconds=60.0, wpm=170) == 170

    def test_rounds_to_nearest_word(self) -> None:
        assert target_word_count(duration_seconds=10.0, wpm=170) == 28  # 28.33 -> 28

    def test_default_wpm_is_170(self) -> None:
        assert target_word_count(duration_seconds=60.0) == 170


class TestEstimatedSeconds:
    def test_known_word_count_and_wpm(self) -> None:
        assert estimated_seconds(word_count=170, wpm=170) == pytest.approx(60.0)

    def test_zero_words_is_zero_seconds(self) -> None:
        assert estimated_seconds(word_count=0, wpm=170) == pytest.approx(0.0)


class TestCountWords:
    def test_simple_sentence(self) -> None:
        assert count_words("Hello there, world.") == 3

    def test_collapses_whitespace(self) -> None:
        assert count_words("  one   two \n three  ") == 3

    def test_empty_string_is_zero(self) -> None:
        assert count_words("") == 0


class TestParseCoordinatedResponse:
    def test_well_formed_response_parses_all_segments(self) -> None:
        response = (
            "===SEGMENT 0===\nFirst clip narration.\n"
            "===SEGMENT 1===\nSecond clip narration.\n"
        )
        result = parse_coordinated_response(response, expected_count=2)
        assert result == {0: "First clip narration.", 1: "Second clip narration."}

    def test_missing_delimiter_returns_none(self) -> None:
        response = "Just some narration text with no markers at all."
        assert parse_coordinated_response(response, expected_count=2) is None

    def test_wrong_segment_count_returns_none(self) -> None:
        response = "===SEGMENT 0===\nOnly one segment.\n"
        assert parse_coordinated_response(response, expected_count=2) is None


class TestGenerateCoordinatedNarration:
    def test_single_call_success(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = (
            "===SEGMENT 0===\nGenerated text for slot 0.\n"
        )
        segments = [SegmentPlan(index=0, fixed_text=None, target_words=10)]
        result = generate_coordinated_narration("Topic", segments, llm)
        assert result == {0: "Generated text for slot 0."}
        assert llm.generate_script.call_count == 1

    def test_retries_once_on_parse_failure_then_succeeds(self) -> None:
        llm = MagicMock()
        llm.generate_script.side_effect = [
            "no delimiters here",
            "===SEGMENT 0===\nRetried text.\n",
        ]
        segments = [SegmentPlan(index=0, fixed_text=None, target_words=10)]
        result = generate_coordinated_narration("Topic", segments, llm)
        assert result == {0: "Retried text."}
        assert llm.generate_script.call_count == 2

    def test_hard_fails_after_two_parse_failures(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "no delimiters here either time"
        segments = [SegmentPlan(index=0, fixed_text=None, target_words=10)]
        with pytest.raises(RuntimeError, match="could not parse"):
            generate_coordinated_narration("Topic", segments, llm)
        assert llm.generate_script.call_count == 2

    def test_only_returns_flagged_slots_not_fixed_ones(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = (
            "===SEGMENT 0===\nFixed text repeated verbatim.\n"
            "===SEGMENT 1===\nNewly generated text.\n"
        )
        segments = [
            SegmentPlan(index=0, fixed_text="Fixed text repeated verbatim.", target_words=0),
            SegmentPlan(index=1, fixed_text=None, target_words=10),
        ]
        result = generate_coordinated_narration("Topic", segments, llm)
        assert result == {1: "Newly generated text."}


class TestPrepareNarrationReview:
    def test_user_written_clip_gets_pace_estimate_no_llm_call(self) -> None:
        llm = MagicMock()
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="One two three four five.")]
        review = prepare_narration_review("Topic", clips, llm, wpm=170.0)
        assert review[0]["text"] == "One two three four five."
        assert review[0]["pace_estimate_seconds"] == pytest.approx(estimated_seconds(5, 170.0))
        llm.generate_script.assert_not_called()

    def test_llm_flagged_clip_gets_generated_text(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "===SEGMENT 0===\nGenerated narration text here.\n"
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, use_llm_generation=True)]
        review = prepare_narration_review("Topic", clips, llm, wpm=170.0)
        assert review[0]["text"] == "Generated narration text here."
        llm.generate_script.assert_called_once()

    def test_mixed_sequence_calls_llm_once_for_all_flagged_clips(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = (
            "===SEGMENT 0===\nUser wrote this.\n"
            "===SEGMENT 1===\nGenerated for slot 1.\n"
        )
        clips = [
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=5.0, script_text="User wrote this."),
            ClipSpec(path="/b.mp4", trim_in=0.0, trim_out=8.0, use_llm_generation=True),
        ]
        review = prepare_narration_review("Topic", clips, llm, wpm=170.0)
        assert review[0]["text"] == "User wrote this."
        assert review[1]["text"] == "Generated for slot 1."
        assert llm.generate_script.call_count == 1
