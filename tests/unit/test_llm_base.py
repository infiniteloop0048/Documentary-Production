"""Unit tests for LLMProvider._chunk_budget and _generate_script_in_chunks."""
from __future__ import annotations

from docu_studio.adapters.llm.base import LLMProvider, _chunk_budget


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
