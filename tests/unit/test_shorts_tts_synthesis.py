"""Unit tests for per-sentence TTS synthesis orchestration.

Focused on call order and file-naming correctness — actual silence-trim/join
audio correctness is covered by test_shorts_tts_join.py, and the real-ffmpeg
gTTS integration path by test_gtts_adapter.py. tts.synthesize and
trim_and_join are both mocked here so these tests stay fast and isolated to
"did the orchestration call the right things in the right order", not
re-verify audio processing already tested elsewhere.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

from docu_studio.shorts.shorts_tts_join import SilenceTrimParams
from docu_studio.shorts.shorts_tts_synthesis import synthesize_sentences_sequential

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
