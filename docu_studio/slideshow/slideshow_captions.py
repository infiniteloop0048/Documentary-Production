"""Burned-in "pop" caption generation for Slideshow: groups word-level
timings into 2-4 word chunks and emits an ASS (Advanced SubStation Alpha)
subtitle document with the currently-spoken word bolded and briefly scaled
up. SlideshowFFmpeg.burn_captions consumes the .ass file this module writes.

Same technique as docu_studio.shorts.shorts_captions, reimplemented
self-contained (own WordTiming, own timing estimate, dimensions parameterized
on the caller's actual out_width/out_height instead of Shorts' hardcoded
1080x1920) per the Phase 1 design decision to keep slideshow/ free of imports
from shorts/.

Word-level timing comes from estimate_word_timestamps() — a character-length-
weighted distribution across the narration's measured duration (Shorts' own
Tier 3 fallback technique), not audio-aligned. Slideshow's TTS adapters expose
no native timestamps and, per the Phase 3 design decision, this phase does not
pull in a Whisper alignment dependency for a first pass at captions — so this
estimate is the only tier here, not one of several.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MIN_GROUP = 2
_MAX_GROUP = 4
_MIN_WORD_DURATION = 0.05  # guards against zero-duration Dialogue lines

# libass resolves this via fontconfig substitution if unavailable on the host,
# giving effectively a system-safe fallback without a literal comma-list.
_FONT_NAME = "DejaVu Sans"

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
    weighting each word's time span by its character length."""
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

    Greedy 4-word chunking, with a borrow-fixup: if the final chunk would be
    a single leftover word, one word is moved over from the second-to-last
    chunk so both end chunks land at >=2. A single-word script is the only
    case returned below the 2-word floor, since there's nothing to borrow.
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
) -> str:
    """Build a full ASS subtitle document from word-level *timings*, sized to
    *out_width*x*out_height* (Slideshow's actual output dimensions, unlike
    Shorts' hardcoded 1080x1920). Events are gapless: each word's Start stays
    at its own estimated timestamp, but its End is pinned to the *next*
    word's Start, so exactly one Dialogue event is ever active. The last
    word's End uses *audio_duration* when given, else its own estimated end.
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
        text = _render_group_text(group, active_index)
        lines.append(
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end_seconds)},"
            f"Pop,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def write_ass_file(
    timings: list[WordTiming],
    output_path: str,
    out_width: int,
    out_height: int,
    audio_duration: float | None = None,
) -> None:
    Path(output_path).write_text(
        generate_ass(timings, out_width, out_height, audio_duration), encoding="utf-8"
    )
