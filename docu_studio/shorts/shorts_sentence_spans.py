"""Pure derivation of sentence-level [start, end] time windows from word-level
timing, used to scope footage cutting to the sentence actually narrating at
any given moment. Works identically regardless of which of the 3 word-timing
tiers (native/whisper/estimated) produced *timestamps* — it only consumes the
WordTiming list, never the tier itself.
"""
from __future__ import annotations

from docu_studio.shorts.capability_resolvers import WordTiming


def sentence_spans(
    sentences: list[str], timestamps: list[WordTiming], total_duration: float,
) -> list[tuple[float, float]]:
    """Return one (start, end) span per sentence in *sentences*, tiling the
    entire [0, total_duration] timeline with no gaps or overlaps.

    Words are consumed from the flat *timestamps* list in sentence order,
    word_count = len(sentence.split()) at a time (the same word-for-word
    alignment invariant used elsewhere in shorts assembly: *timestamps* is
    assumed to line up with the concatenation of *sentences*). A sentence's
    raw span is [first word's start, last word's end]; if fewer timestamps
    remain than the sentence needs (a tier-2/3 mismatch), the sentence
    collapses to a zero-length anchor at the previous sentence's end rather
    than raising.

    Raw spans are then tiled contiguously: sentence i's *returned* end is
    sentence i+1's raw start (the inter-sentence pause is assigned to the
    earlier sentence, so footage keeps rolling through it), and the last
    sentence's end is *total_duration* (covering any trailing silence). This
    guarantees sum(end - start for start, end in spans) == total_duration
    exactly, so segments generated within each span always cover the full
    narration with no dead frames between sentences.
    """
    if not sentences:
        return []

    raw_starts: list[float] = []
    raw_ends: list[float] = []
    cursor = 0
    for sentence in sentences:
        word_count = len(sentence.split())
        if word_count == 0 or cursor >= len(timestamps):
            anchor = raw_ends[-1] if raw_ends else 0.0
            raw_starts.append(anchor)
            raw_ends.append(anchor)
            continue
        words = timestamps[cursor:cursor + word_count]
        raw_starts.append(words[0].start)
        raw_ends.append(words[-1].end)
        cursor += word_count

    spans: list[tuple[float, float]] = []
    prev_end = 0.0
    last = len(raw_ends) - 1
    for i, raw_end in enumerate(raw_ends):
        end = total_duration if i == last else raw_starts[i + 1]
        end = max(end, prev_end)
        spans.append((prev_end, end))
        prev_end = end
    return spans
