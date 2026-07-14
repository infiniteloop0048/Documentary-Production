"""Unit tests for per-sentence TTS synthesis orchestration.

Focused on call order and file-naming correctness — actual silence-trim/join
audio correctness is covered by test_shorts_tts_join.py, and the real-ffmpeg
gTTS integration path by test_gtts_adapter.py. tts.synthesize and
trim_and_join are both mocked here so these tests stay fast and isolated to
"did the orchestration call the right things in the right order", not
re-verify audio processing already tested elsewhere.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from docu_studio.shorts.shorts_tts_join import SilenceTrimParams
from docu_studio.shorts.shorts_tts_synthesis import (
    synthesize_sentences_concurrent,
    synthesize_sentences_sequential,
)

_PARAMS = SilenceTrimParams()


class TestSynthesizeSentencesSequential:
    def test_calls_synthesize_once_per_sentence_in_order(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, path: Path(path).write_bytes(b"x") or 1.0
        sentences = ["First sentence.", "Second sentence.", "Third sentence."]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_sequential(
                tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS,
            )

        assert tts.synthesize.call_count == 3
        called_texts = [c.args[0] for c in tts.synthesize.call_args_list]
        assert called_texts == sentences
        mock_join.assert_called_once()

    def test_writes_each_sentence_to_its_own_indexed_file(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, path: Path(path).write_bytes(b"x") or 1.0
        sentences = ["Alpha.", "Beta."]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_sequential(
                tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS,
            )

        joined_input_paths = mock_join.call_args.args[0]
        assert len(joined_input_paths) == 2
        assert joined_input_paths[0].name < joined_input_paths[1].name  # sentence 0 sorts before 1
        for p in joined_input_paths:
            assert p.exists()

    def test_join_called_with_sentence_order_not_completion_order(self, tmp_path: Path) -> None:
        """Sequential synthesis has no completion-order ambiguity (each call
        blocks until done before the next starts), but the join input list
        must still be in script order — this is the baseline the Phase 2
        concurrent dispatchers must also satisfy."""
        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, path: Path(path).write_bytes(b"x") or 1.0
        sentences = [f"Sentence {i}." for i in range(5)]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_sequential(
                tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS,
            )

        joined_input_paths = mock_join.call_args.args[0]
        names = [p.name for p in joined_input_paths]
        assert names == sorted(names)

    def test_passes_join_params_and_output_path_through(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, path: Path(path).write_bytes(b"x") or 1.0
        output_path = str(tmp_path / "final.mp3")

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_sequential(tts, ["Only sentence."], tmp_path, output_path, _PARAMS)

        mock_join.assert_called_once_with(mock_join.call_args.args[0], output_path, _PARAMS)

    def test_single_sentence_still_joins(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, path: Path(path).write_bytes(b"x") or 1.0

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_sequential(
                tts, ["Only one."], tmp_path, str(tmp_path / "final.mp3"), _PARAMS,
            )

        assert tts.synthesize.call_count == 1
        mock_join.assert_called_once()


class TestSynthesizeSentencesConcurrent:
    def test_calls_synthesize_once_per_sentence(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, path: Path(path).write_bytes(b"x") or 1.0
        sentences = ["First sentence.", "Second sentence.", "Third sentence."]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_concurrent(
                tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS, max_concurrency=2,
            )

        assert tts.synthesize.call_count == 3
        called_texts = sorted(c.args[0] for c in tts.synthesize.call_args_list)
        assert called_texts == sorted(sentences)
        mock_join.assert_called_once()

    def test_never_exceeds_max_concurrency_in_flight(self, tmp_path: Path) -> None:
        """Regression guard for the concurrency cap itself: with
        max_concurrency=2, no more than 2 synthesize() calls may be actively
        running at the same instant, even though there are more sentences
        than that."""
        in_flight = 0
        max_observed = 0
        lock = threading.Lock()

        def tracked_synthesize(text: str, path: str) -> float:
            nonlocal in_flight, max_observed
            with lock:
                in_flight += 1
                max_observed = max(max_observed, in_flight)
            time.sleep(0.05)
            Path(path).write_bytes(b"x")
            with lock:
                in_flight -= 1
            return 1.0

        tts = MagicMock()
        tts.synthesize.side_effect = tracked_synthesize
        sentences = [f"Sentence {i}." for i in range(6)]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join"):
            synthesize_sentences_concurrent(
                tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS, max_concurrency=2,
            )

        assert max_observed <= 2
        assert max_observed >= 2, "test didn't actually exercise concurrency — check timing"

    def test_out_of_order_completion_still_joins_in_script_order(self, tmp_path: Path) -> None:
        """The ordering guarantee: network calls complete in arbitrary order
        under concurrency — deliberately make sentence 0 finish LAST (it
        sleeps while later sentences complete immediately) and confirm the
        join input list is still index-ordered, not completion-ordered."""
        def slow_first_synthesize(text: str, path: str) -> float:
            if text.startswith("First"):
                time.sleep(0.15)
            Path(path).write_bytes(b"x")
            return 1.0

        tts = MagicMock()
        tts.synthesize.side_effect = slow_first_synthesize
        sentences = ["First sentence.", "Second sentence.", "Third sentence."]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_concurrent(
                tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS, max_concurrency=3,
            )

        joined_input_paths = mock_join.call_args.args[0]
        assert [p.name for p in joined_input_paths] == [
            "sentence_000.mp3", "sentence_001.mp3", "sentence_002.mp3",
        ]

    def test_max_concurrency_one_behaves_like_sequential_ordering(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, path: Path(path).write_bytes(b"x") or 1.0
        sentences = [f"Sentence {i}." for i in range(4)]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join") as mock_join:
            synthesize_sentences_concurrent(
                tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS, max_concurrency=1,
            )

        joined_input_paths = mock_join.call_args.args[0]
        names = [p.name for p in joined_input_paths]
        assert names == sorted(names)

    def test_propagates_exception_from_a_failed_sentence(self, tmp_path: Path) -> None:
        tts = MagicMock()

        def flaky(text: str, path: str) -> float:
            if text.startswith("Second"):
                raise RuntimeError("synthesis failed")
            Path(path).write_bytes(b"x")
            return 1.0

        tts.synthesize.side_effect = flaky
        sentences = ["First.", "Second.", "Third."]

        with patch("docu_studio.shorts.shorts_tts_synthesis.trim_and_join"):
            try:
                synthesize_sentences_concurrent(
                    tts, sentences, tmp_path, str(tmp_path / "final.mp3"), _PARAMS, max_concurrency=2,
                )
                raise AssertionError("expected RuntimeError to propagate")
            except RuntimeError as exc:
                assert "synthesis failed" in str(exc)
