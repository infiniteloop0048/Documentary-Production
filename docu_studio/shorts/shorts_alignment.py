"""Sequence alignment: match Whisper's transcribed words against the known
script text, interpolating timing for any word Whisper missed or misheard.

The matcher (align_words_to_script / _interpolate) is pure — no faster-whisper
import here — so it's directly unit-testable against fake Whisper output.
run_tier2_alignment is the only part of this module that touches faster-whisper,
and it does so via a lazy import inside _run_whisper.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from docu_studio.shorts.capability_resolvers import WordTiming

# Minimum span given to any interpolated (unmatched) word, so a run of
# unmatched words never collapses to identical/zero-duration timestamps.
# Matches captions.py's _MIN_WORD_DURATION floor in spirit, but kept as an
# independent constant since interpolation and ASS-rendering are separate
# concerns that shouldn't be coupled by a shared import.
_MIN_INTERP_WORD_SPAN = 0.05


def _normalize_word(word: str) -> str:
    """Lowercase and strip surrounding punctuation for matching purposes."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", word.lower())


def align_words_to_script(
    script_words: list[str],
    whisper_words: list[tuple[str, float, float]],
) -> tuple[list[WordTiming], float]:
    """Return (timings, fraction_matched) — one WordTiming per *script_words*
    entry, in order, aligned to *whisper_words* = [(word, start, end), ...].

    Forward-scans whisper_words for a normalized match to each script word in
    turn, never re-matching an earlier whisper word (so repeated words align
    positionally rather than all snapping to the first occurrence). Unmatched
    script words are filled in by _interpolate() using their matched neighbors.
    """
    n = len(script_words)
    matched: list[tuple[float, float] | None] = [None] * n
    whisper_cursor = 0
    match_count = 0

    for i, sw in enumerate(script_words):
        target = _normalize_word(sw)
        found = None
        for j in range(whisper_cursor, len(whisper_words)):
            w, start, end = whisper_words[j]
            if _normalize_word(w) == target:
                found = (start, end)
                whisper_cursor = j + 1
                break
        if found is not None:
            matched[i] = found
            match_count += 1

    fraction_matched = (match_count / n) if n else 0.0
    timings = _interpolate(script_words, matched)
    return timings, fraction_matched


def _interpolate(
    script_words: list[str], matched: list[tuple[float, float] | None]
) -> list[WordTiming]:
    """Fill in timing for unmatched words by linear interpolation between the
    nearest matched neighbors.

    Every unmatched run is given a strictly positive, evenly-spaced span of
    at least _MIN_INTERP_WORD_SPAN per word, so no run ever collapses to
    identical/zero-duration timestamps (the previous behavior, which produced
    overlapping/duplicate ASS caption cues downstream — see the shorts
    subtitle-blinking investigation). Leading runs are back-filled from the
    first matched word's start; trailing runs are forward-filled from the
    last matched word's end; middle runs whose matched neighbors leave no
    positive span (left.end >= right.start — e.g. a misordered Whisper
    match) are forward-filled from left.end the same way a trailing run
    would be, since the right bound can't be trusted to leave room. A middle
    run with a genuinely positive but too-tight span is widened to the
    minimum instead of using the tight span directly. If nothing matched at
    all, returns an all-zero-duration timeline — get_word_timestamps' caller
    is expected to fall back to Tier 3 rather than rely on this in practice,
    but it stays well-defined here regardless."""
    n = len(script_words)
    if n == 0:
        return []

    if not any(matched):
        return [WordTiming(word=w, start=0.0, end=0.0) for w in script_words]

    result: list[WordTiming | None] = [None] * n
    for i, m in enumerate(matched):
        if m is not None:
            result[i] = WordTiming(word=script_words[i], start=m[0], end=m[1])

    i = 0
    while i < n:
        if result[i] is not None:
            i += 1
            continue
        j = i
        while j < n and result[j] is None:
            j += 1
        left = result[i - 1] if i > 0 else None
        right = result[j] if j < n else None
        count = j - i
        min_span = count * _MIN_INTERP_WORD_SPAN

        if left is None and right is None:
            span_start, span_end = 0.0, min_span  # unreachable given the any(matched) guard
        elif left is None:
            span_end = right.start
            span_start = max(0.0, span_end - min_span)
        elif right is None or left.end >= right.start:
            span_start = left.end
            span_end = span_start + min_span
        else:
            span_start, span_end = left.end, right.start
            if span_end - span_start < min_span:
                span_end = span_start + min_span

        step = (span_end - span_start) / count
        for k in range(count):
            w_start = span_start + step * k
            w_end = span_start + step * (k + 1)
            result[i + k] = WordTiming(word=script_words[i + k], start=w_start, end=w_end)
        i = j

    return result  # type: ignore[return-value]


_TIER2_TIMEOUT_SECONDS = 60.0


def _model_cache_dir() -> str:
    from platformdirs import user_cache_dir

    return str(Path(user_cache_dir("docu_studio")) / "whisper_models")


def _run_whisper(audio_path: str) -> list[tuple[str, float, float]]:
    from faster_whisper import WhisperModel  # lazy import — heavy optional dep

    import logging

    logging.getLogger(__name__).info(
        "Tier 2 alignment: loading Whisper model (first use downloads ~75MB)…"
    )
    model = WhisperModel(
        "tiny", device="cpu", compute_type="int8", download_root=_model_cache_dir(),
    )
    segments, _info = model.transcribe(audio_path, word_timestamps=True)
    words: list[tuple[str, float, float]] = []
    for segment in segments:
        for w in segment.words or []:
            words.append((w.word, w.start, w.end))
    return words


def run_tier2_alignment(audio_path: str, script_text: str) -> tuple[list[WordTiming], float]:
    """Run Whisper word-level transcription on *audio_path* and align it to the
    known *script_text*. Raises on any failure — missing dependency, model/
    transcription error, or a hard 60s timeout — callers must catch and fall
    back to Tier 3; a shorts run must never fail because of alignment."""
    result_box: dict[str, object] = {}

    def _worker() -> None:
        try:
            result_box["words"] = _run_whisper(audio_path)
        except Exception as exc:  # noqa: BLE001 - surfaced via result_box, not raised in-thread
            result_box["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=_TIER2_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise TimeoutError(
            f"Tier 2 whisper alignment exceeded {_TIER2_TIMEOUT_SECONDS:.0f}s timeout"
        )
    if "error" in result_box:
        raise result_box["error"]  # type: ignore[misc]

    whisper_words = result_box.get("words", [])
    script_words = script_text.split()
    return align_words_to_script(script_words, whisper_words)  # type: ignore[arg-type]
