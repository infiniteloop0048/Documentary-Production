"""Unit tests for LLMProvider._chunk_budget and _generate_script_in_chunks."""
from __future__ import annotations

from docu_studio.adapters.llm.base import (
    LLMProvider,
    _chunk_budget,
    _strip_leading_duplicate_sentence,
)


class TestChunkBudget:
    def test_scales_up_for_large_target(self) -> None:
        assert _chunk_budget(18000) > _chunk_budget(4500)

    def test_reasonable_for_small_target(self) -> None:
        # 4500 words (30 min @ 150 wpm) is the empirically-tested case that used
        # to rely on the old fixed constant of 6 chunks — budget should still land there.
        assert _chunk_budget(4500) == 6

    def test_capped_at_ceiling_for_pathological_target(self) -> None:
        assert _chunk_budget(1_000_000) <= 20


class TestGenerateScriptInChunksDiminishingReturns:
    def test_early_exit_triggers_on_tiny_chunk_contribution(self) -> None:
        # First chunk contributes a healthy 1100/4500 words (no trigger), second
        # chunk contributes only 50 words while still far short of target — that's
        # a plateau signal and generation should stop rather than burn more chunks.
        calls = []

        def generate_chunk(script_so_far: str, words_needed: int) -> str:
            calls.append(words_needed)
            if not script_so_far:
                return "word " * 1100
            return "word " * 50

        triggered: list[int] = []
        script = LLMProvider._generate_script_in_chunks(
            4500, generate_chunk, on_diminishing_returns=triggered.append
        )

        assert len(calls) == 2, "should stop after the tiny second chunk, not keep retrying"
        assert triggered, "expected on_diminishing_returns to fire"
        assert triggered[0] == 4500 - len(script.split())

    def test_early_exit_does_not_trigger_on_meaningful_slow_progress(self) -> None:
        # Every chunk contributes 900/4500 (20%) — well above the diminishing-returns
        # floor — so the loop should keep going until the target is reached, not bail.
        def generate_chunk(script_so_far: str, words_needed: int) -> str:
            return "word " * 900

        triggered: list[int] = []
        script = LLMProvider._generate_script_in_chunks(
            4500, generate_chunk, on_diminishing_returns=triggered.append
        )

        assert not triggered, "should not treat steady meaningful progress as diminishing returns"
        assert len(script.split()) >= 4500 * 0.9

    def test_drops_continuation_chunk_that_restates_last_sentence(self) -> None:
        # Reproduces the observed DeepSeek behavior: continuation chunk opens by
        # repeating the exact sentence the prior chunk ended on, despite the
        # prompt instructing it not to repeat prior content. Filler word counts
        # are sized to clear the diminishing-returns floor for target=60, so the
        # loop calls generate_chunk twice rather than giving up after one.
        calls = []
        first_chunk = ("Word " * 30).strip() + ". The falls are disappearing."
        second_chunk_raw = "The falls are disappearing. Each foot brings the end closer today."

        def generate_chunk(script_so_far: str, words_needed: int) -> str:
            calls.append(script_so_far)
            return first_chunk if not script_so_far else second_chunk_raw

        script = LLMProvider._generate_script_in_chunks(60, generate_chunk)

        assert len(calls) == 2
        assert script.count("The falls are disappearing.") == 1
        assert script.endswith("Each foot brings the end closer today.")


class TestStripLeadingDuplicateSentence:
    def test_strips_exact_restated_sentence(self) -> None:
        result = _strip_leading_duplicate_sentence(
            "Foo bar. The falls are disappearing.",
            "The falls are disappearing. Each foot brings the end closer.",
        )
        assert result == "Each foot brings the end closer."

    def test_strips_case_and_punctuation_insensitively(self) -> None:
        result = _strip_leading_duplicate_sentence(
            "The Falls Are Disappearing!",
            "the falls are disappearing. New content here.",
        )
        assert result == "New content here."

    def test_leaves_chunk_untouched_when_no_overlap(self) -> None:
        result = _strip_leading_duplicate_sentence(
            "First sentence here.", "Second sentence here."
        )
        assert result == "Second sentence here."

    def test_returns_empty_when_chunk_is_only_the_duplicate(self) -> None:
        result = _strip_leading_duplicate_sentence(
            "The falls are disappearing.", "The falls are disappearing."
        )
        assert result == ""
