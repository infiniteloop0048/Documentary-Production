"""Layer 1 of the duration-fit algorithm: word-count targeting from duration, plus
the one coordinated LLM call for all use_llm_generation=True clips in a sequence,
given the full sequence (including fixed user-written text as context) so the
narration reads continuously across cuts. See docs/superpowers/specs/
2026-07-13-clipstory-phase1-design.md for the full rationale.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.clipstory.clipstory_config import ClipSpec
from docu_studio.common.tts_calibration import get_wpm

_log = logging.getLogger(__name__)

CLIPSTORY_DEFAULT_WPM = 170
_SEGMENT_DELIMITER_RE = re.compile(r"===SEGMENT (\d+)===")


def target_word_count(duration_seconds: float, wpm: float = CLIPSTORY_DEFAULT_WPM) -> int:
    return round(duration_seconds / 60 * wpm)


def estimated_seconds(word_count: int, wpm: float = CLIPSTORY_DEFAULT_WPM) -> float:
    return word_count / wpm * 60


def count_words(text: str) -> int:
    return len(text.split())


@dataclass(frozen=True)
class SegmentPlan:
    index: int
    fixed_text: str | None  # None means: this slot needs LLM generation
    target_words: int


def build_coordinated_prompt(topic: str, segments: list[SegmentPlan]) -> str:
    lines = [
        f"You are writing narration for a multi-clip video about: {topic}",
        "",
        "The video is made of the following ordered clips. Some already have fixed "
        "narration text that you must NOT change — treat it as context establishing "
        "continuity. Others need you to write new narration that continues naturally "
        "from the surrounding fixed text.",
        "",
    ]
    for seg in segments:
        if seg.fixed_text is not None:
            lines.append(f"Clip {seg.index}: FIXED TEXT (repeat verbatim) — \"{seg.fixed_text}\"")
        else:
            lines.append(
                f"Clip {seg.index}: WRITE NEW NARRATION — target approximately "
                f"{seg.target_words} words."
            )
    lines += [
        "",
        "OUTPUT FORMAT (mandatory):",
        "For every clip listed above, in order, output a line of the exact form "
        "'===SEGMENT n===' (where n is that clip's number) immediately followed by "
        "its narration text — for FIXED TEXT clips, repeat the fixed text verbatim; "
        "for WRITE NEW NARRATION clips, write the new narration there.",
        "Plain spoken text only. No markdown, no headers, no bullet points, no "
        "quotation marks around the text.",
        "Write only the segments in the format above — nothing else.",
    ]
    return "\n".join(lines)


def parse_coordinated_response(response: str, expected_count: int) -> dict[int, str] | None:
    """Split *response* by '===SEGMENT n===' markers. Returns {index: text} only if
    exactly *expected_count* segments were found — never guess-splits a partial match."""
    matches = list(_SEGMENT_DELIMITER_RE.finditer(response))
    if len(matches) != expected_count:
        _log.warning(
            "Clip Story coordinated response segment count mismatch: got %d, expected %d",
            len(matches), expected_count,
        )
        return None
    result: dict[int, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(response)
        result[int(m.group(1))] = response[start:end].strip()
    return result


def generate_coordinated_narration(
    topic: str, segments: list[SegmentPlan], llm: LLMProvider
) -> dict[int, str]:
    """Run the one coordinated LLM call for all *segments* with fixed_text=None,
    returning {index: generated_text} for those slots only. One retry on a parse
    mismatch, then a hard RuntimeError — never guess-splits."""
    prompt = build_coordinated_prompt(topic, segments)
    total_target_words = sum(seg.target_words for seg in segments if seg.fixed_text is None)

    response = llm.generate_script(topic=prompt, target_words=total_target_words)
    parsed = parse_coordinated_response(response, len(segments))
    if parsed is None:
        _log.info("Clip Story coordinated narration parse failed, retrying once")
        response = llm.generate_script(topic=prompt, target_words=total_target_words)
        parsed = parse_coordinated_response(response, len(segments))
    if parsed is None:
        raise RuntimeError(
            f"Clip Story coordinated narration generation failed: could not parse "
            f"{len(segments)} segments from the LLM response after 2 attempts."
        )
    return {seg.index: parsed[seg.index] for seg in segments if seg.fixed_text is None}


def prepare_narration_review(
    topic: str, clips: list[ClipSpec], llm: LLMProvider, wpm: float
) -> dict[int, dict]:
    """Layer 1 review-step orchestration: target word counts from each clip's
    trim-arithmetic duration estimate, one coordinated LLM call for flagged clips,
    and a pace estimate for every clip's final text — everything the GUI needs to
    show before any TTS/ffmpeg work runs."""
    segments = [
        SegmentPlan(
            index=i,
            fixed_text=None if clip.use_llm_generation else clip.script_text,
            target_words=target_word_count(clip.duration_estimate, wpm),
        )
        for i, clip in enumerate(clips)
    ]
    generated: dict[int, str] = {}
    if any(seg.fixed_text is None for seg in segments):
        generated = generate_coordinated_narration(topic, segments, llm)

    review: dict[int, dict] = {}
    for i, clip in enumerate(clips):
        text = generated.get(i, clip.script_text)
        review[i] = {
            "text": text,
            "pace_estimate_seconds": estimated_seconds(count_words(text), wpm),
        }
    return review
