"""Per-sentence TTS synthesis orchestration.

Synthesizing once per sentence (instead of once for the whole script) scopes
each sentence's own lead-in silence — and any Whisper first-word-miss that
silence can cause — to that one sentence, rather than sharing a single
whole-script timeline. See the Task 4 design discussion for the full
reasoning.

Two dispatch strategies:
- synthesize_sentences_sequential (Phase 1): one call at a time. Used for
  gTTS, deliberately — concurrent load is a plausible way to make its own
  documented flakiness worse, not better (Task 4 Section 1).
- synthesize_sentences_concurrent (Phase 2): up to *max_concurrency* calls
  in flight. Used for ElevenLabs (cap-1 — functionally sequential, but
  through the same mechanism so a future tier-adaptive cap doesn't need a
  new code path) and Deepgram (cap-2, per its confirmed rate-limit margin).

Both write each sentence to its own indexed file and hand the *index-ordered*
list to trim_and_join — network calls under concurrency complete in whatever
order the provider returns them, but the join must not: sentence_paths is a
pre-sized list keyed by sentence index, so the natural data structure
enforces correct ordering rather than relying on any explicit re-sort after
the fact.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


def synthesize_sentences_concurrent(
    tts: TTSProvider,
    sentences: list[str],
    work_dir: Path,
    output_path: str,
    join_params: SilenceTrimParams,
    max_concurrency: int,
) -> None:
    """Synthesize each of *sentences* via *tts*, running up to
    *max_concurrency* synthesize() calls in flight at once, then trim+join
    the results in *script order* (by sentence index) into *output_path*
    regardless of which call actually completed first.

    Each worker writes into its own pre-assigned slot in an index-sized
    list — never appends — so out-of-order completion can't disturb join
    order. Any exception from any sentence propagates (via Future.result())
    rather than being silently dropped."""
    sentence_paths: list[Path | None] = [None] * len(sentences)

    def _synthesize_one(idx: int, sentence: str) -> None:
        sentence_path = work_dir / f"sentence_{idx:03d}.mp3"
        tts.synthesize(sentence, str(sentence_path))
        sentence_paths[idx] = sentence_path

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = [
            executor.submit(_synthesize_one, idx, sentence)
            for idx, sentence in enumerate(sentences)
        ]
        for future in futures:
            future.result()

    trim_and_join(sentence_paths, output_path, join_params)  # type: ignore[arg-type]
