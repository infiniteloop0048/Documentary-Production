"""Per-sentence TTS synthesis orchestration.

Synthesizing once per sentence (instead of once for the whole script) scopes
each sentence's own lead-in silence — and any Whisper first-word-miss that
silence can cause — to that one sentence, rather than sharing a single
whole-script timeline. See the Task 4 design discussion for the full
reasoning; this module is the sequential (Phase 1) dispatch strategy. Phase 2
adds bounded-concurrency variants for adapters that support it, sharing this
module's file-naming and trim_and_join wiring.
"""
from __future__ import annotations

from pathlib import Path

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.shorts.shorts_tts_join import SilenceTrimParams, trim_and_join


def synthesize_sentences_sequential(
    tts: TTSProvider,
    sentences: list[str],
    work_dir: Path,
    output_path: str,
    join_params: SilenceTrimParams,
) -> None:
    """Synthesize each of *sentences* via *tts* one at a time, in order,
    writing each to its own indexed file under *work_dir*, then trim+join
    them into *output_path*.

    Sequential dispatch: each synthesize() call blocks until complete before
    the next starts, so the resulting file list is trivially in script order
    — no ordering reconciliation needed (unlike Phase 2's concurrent
    dispatchers, which must sort by sentence index before joining)."""
    sentence_paths: list[Path] = []
    for idx, sentence in enumerate(sentences):
        sentence_path = work_dir / f"sentence_{idx:03d}.mp3"
        tts.synthesize(sentence, str(sentence_path))
        sentence_paths.append(sentence_path)

    trim_and_join(sentence_paths, output_path, join_params)
