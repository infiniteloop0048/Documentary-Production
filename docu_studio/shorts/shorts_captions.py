"""Burned-in "pop" caption generation: groups word-level timings into 2-4 word
chunks and emits an ASS (Advanced SubStation Alpha) subtitle document with the
currently-spoken word bolded and briefly scaled up.

Pure text generation — no ffmpeg or subprocess calls here; ShortsFFmpeg.burn_captions
consumes the .ass file this module writes.
"""
from __future__ import annotations

from pathlib import Path

from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_config import SHORTS_HEIGHT, SHORTS_WIDTH

_MIN_GROUP = 2
_MAX_GROUP = 4

# Platform UI (like/comment/share rail, captions toggle) covers the literal
# bottom 15% of a Short/Reel — 22% clears that with margin to spare while
# still reading as "lower-middle", not centered.
SAFE_AREA_BOTTOM_MARGIN = round(SHORTS_HEIGHT * 0.22)

# libass resolves this via fontconfig substitution if unavailable on the host,
# giving effectively a system-safe fallback without a literal comma-list (an
# ASS style line takes exactly one Fontname, unlike CSS font-family).
_FONT_NAME = "DejaVu Sans"

_MIN_WORD_DURATION = 0.05  # guards against zero-duration Dialogue lines

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
                r"{\t(0,120,\fscx118\fscy118)\t(120,240,\fscx100\fscy100)\b1}"
                + word_text + r"{\r}"
            )
        else:
            parts.append(word_text)
    return " ".join(parts)


def generate_ass(timings: list[WordTiming]) -> str:
    """Build a full ASS subtitle document from word-level *timings*: words are
    grouped into 2-4 word "pop caption" chunks, the currently-spoken word in
    each chunk is bold and briefly scaled up via an ASS \\t transform, and
    every line sits inside the lower-middle safe area."""
    header = _ASS_HEADER_TEMPLATE.format(
        width=SHORTS_WIDTH, height=SHORTS_HEIGHT,
        font=_FONT_NAME, margin_v=SAFE_AREA_BOTTOM_MARGIN,
    )
    lines = [header]
    for group in group_words(timings):
        for active_index, word in enumerate(group):
            start = _format_ass_time(word.start)
            end_seconds = max(word.end, word.start + _MIN_WORD_DURATION)
            end = _format_ass_time(end_seconds)
            text = _render_group_text(group, active_index)
            lines.append(f"Dialogue: 0,{start},{end},Pop,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def write_ass_file(timings: list[WordTiming], output_path: str) -> None:
    Path(output_path).write_text(generate_ass(timings), encoding="utf-8")
