"""Burned-in "pop" caption generation, shared by the Shorts and Slideshow
pipelines: groups word-level timings into 2-4 word chunks and emits an ASS
(Advanced SubStation Alpha) subtitle document with the currently-spoken word
bolded and briefly scaled up.

Pure text generation — no ffmpeg or subprocess calls here; ShortsFFmpeg's and
SlideshowFFmpeg's burn_captions methods both consume the .ass file this
module writes.

Word-level timing can come from a real alignment tier (Shorts' native-TTS /
Whisper tiers, resolved in docu_studio.shorts.capability_resolvers, which is
Shorts-only) or from estimate_word_timestamps() below — a character-length-
weighted distribution across the narration's measured duration. This is
Shorts' Tier 3 fallback and Slideshow's only tier (Slideshow's TTS adapters
expose no native timestamps and, per the Phase 3 design decision, this phase
does not pull in a Whisper alignment dependency for a first pass at
captions).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MIN_GROUP = 2
_MAX_GROUP = 4
_MIN_WORD_DURATION = 0.05  # guards against zero-duration Dialogue lines

# libass resolves this via fontconfig substitution if unavailable on the host,
# giving effectively a system-safe fallback without a literal comma-list (an
# ASS style line takes exactly one Fontname, unlike CSS font-family).
_FONT_NAME = "DejaVu Sans"

# Platform UI (like/comment/share rail, captions toggle) covers the literal
# bottom 15% of a Short/Reel — 22% clears that with margin to spare while
# still reading as "lower-middle", not centered. Expressed as a fraction of
# out_height (rather than a baked pixel constant) so the same margin ratio
# holds across callers' differing output dimensions.
_SAFE_AREA_BOTTOM_FRACTION = 0.22

_ASS_HEADER_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{font},64,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float
    end: float


def estimate_word_timestamps(script_text: str, duration: float) -> list[WordTiming]:
    """Distribute the words of *script_text* across *duration* seconds,
    weighting each word's time span by its character length (Tier 3 — no
    audio analysis)."""
    words = script_text.split()
    if not words or duration <= 0:
        return []
    weights = [len(w) for w in words]
    total_weight = sum(weights)
    timestamps: list[WordTiming] = []
    cursor = 0.0
    for word, weight in zip(words, weights):
        span = duration * (weight / total_weight)
        timestamps.append(WordTiming(word=word, start=cursor, end=cursor + span))
        cursor += span
    return timestamps


def group_words(timings: list[WordTiming]) -> list[list[WordTiming]]:
    """Split *timings* into 2-4 word "pop caption" chunks.

    Greedy 4-word chunking, with a borrow-fixup: if the final chunk would be a
    single leftover word, one word is moved over from the second-to-last chunk
    so both end chunks land at >=2 (e.g. n=13 -> [4,4,4,1] -> [4,4,3,2]). A
    single-word script is the only case returned below the 2-word floor, since
    there's nothing left to borrow from.
    """
    n = len(timings)
    if n == 0:
        return []
    if n == 1:
        return [list(timings)]

    groups: list[list[WordTiming]] = []
    i = 0
    while i < n:
        chunk = timings[i:i + _MAX_GROUP]
        groups.append(list(chunk))
        i += len(chunk)

    if len(groups[-1]) < _MIN_GROUP and len(groups) > 1:
        borrowed = groups[-2].pop()
        groups[-1].insert(0, borrowed)

    return groups


def _escape_ass_text(word: str) -> str:
    return word.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_cs = round(seconds * 100)
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _render_group_text(group: list[WordTiming], active_index: int) -> str:
    parts = []
    for idx, w in enumerate(group):
        word_text = _escape_ass_text(w.word)
        if idx == active_index:
            parts.append(
                r"{\t(0,60,\fscx118\fscy118)\t(60,120,\fscx100\fscy100)\b1}"
                + word_text + r"{\r}"
            )
        else:
            parts.append(word_text)
    return " ".join(parts)


def generate_ass(
    timings: list[WordTiming],
    out_width: int,
    out_height: int,
    audio_duration: float | None = None,
    punch_window: tuple[float, float] | None = None,
) -> str:
    """Build a full ASS subtitle document from word-level *timings*, sized to
    *out_width*x*out_height* (the caller's actual output dimensions): words
    are grouped into 2-4 word "pop caption" chunks, the currently-spoken word
    in each chunk is bold and briefly scaled up via an ASS \\t transform, and
    every line sits inside the lower-middle safe area.

    Events are gapless: each word's Start stays at its own timestamp, but its
    End is pinned to the *next* word's Start (across group boundaries too),
    so exactly one Dialogue event is ever active — no flicker between words
    and no double-blink at group swaps. The very last word's End uses
    *audio_duration* when given, else falls back to its own timing's end.

    *punch_window*, if given, is (card_start, card_end) in seconds: any event
    fully inside that window is dropped (the punch card carries its own text,
    so no caption should double up on it), any event partially overlapping it
    is clamped to whichever edge it crosses, an event whose span fully
    straddles the window (starts before card_start and ends after card_end)
    is split into two Dialogue lines — one for the span before the card, one
    for the span after — so its word/group caption isn't lost entirely, and
    events entirely outside it are untouched. Gaplessness is only guaranteed
    among the remaining events themselves — a gap at the card's own window is
    expected and correct.
    """
    margin_v = round(out_height * _SAFE_AREA_BOTTOM_FRACTION)
    header = _ASS_HEADER_TEMPLATE.format(
        width=out_width, height=out_height, font=_FONT_NAME, margin_v=margin_v,
    )
    lines = [header]
    groups = group_words(timings)
    flat: list[tuple[list[WordTiming], int, WordTiming]] = [
        (group, active_index, word)
        for group in groups
        for active_index, word in enumerate(group)
    ]
    for i, (group, active_index, word) in enumerate(flat):
        start = word.start
        if i + 1 < len(flat):
            next_start = flat[i + 1][2].start
        elif audio_duration is not None:
            next_start = audio_duration
        else:
            next_start = word.end
        end_seconds = max(next_start, start + _MIN_WORD_DURATION)

        if punch_window is not None:
            card_start, card_end = punch_window
            if start >= card_end or end_seconds <= card_start:
                segments_to_emit = [(start, end_seconds)]  # fully outside — unaffected
            elif start >= card_start and end_seconds <= card_end:
                segments_to_emit = []  # fully inside the card window — drop this event
            elif start < card_start and end_seconds > card_end:
                # the window is a sub-interval of this event's own span — split
                # into a before-card and an after-card occurrence instead of
                # truncating away the tail beyond the far edge.
                segments_to_emit = [(start, card_start), (card_end, end_seconds)]
            elif start < card_start:
                segments_to_emit = [(start, card_start)]
            else:
                segments_to_emit = [(card_end, end_seconds)]
        else:
            segments_to_emit = [(start, end_seconds)]

        text = _render_group_text(group, active_index)
        for seg_start, seg_end in segments_to_emit:
            if seg_end <= seg_start:
                continue  # defensive — structurally unreachable given the branches above
            lines.append(
                f"Dialogue: 0,{_format_ass_time(seg_start)},{_format_ass_time(seg_end)},"
                f"Pop,,0,0,0,,{text}"
            )
    return "\n".join(lines) + "\n"


def write_ass_file(
    timings: list[WordTiming],
    output_path: str,
    out_width: int,
    out_height: int,
    audio_duration: float | None = None,
    punch_window: tuple[float, float] | None = None,
) -> None:
    Path(output_path).write_text(
        generate_ass(timings, out_width, out_height, audio_duration, punch_window),
        encoding="utf-8",
    )
