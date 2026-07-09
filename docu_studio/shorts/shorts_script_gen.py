"""Dedicated script generation for Shorts/Reels: cold-open hook, TTS-safe output,
per-sentence visual search queries.

Reuses only LLMProvider's public methods (generate_script, break_into_scenes) —
no adapter files are edited. See the plan's Global Constraints for why
break_into_scenes is repurposed to obtain structured per-sentence JSON.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.shorts.shorts_tts_calibration import get_wpm

_log = logging.getLogger(__name__)

SHORTS_WPM = 170

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def target_word_count(duration_seconds: int, wpm: float = SHORTS_WPM) -> int:
    """Return the target word count for *duration_seconds* at *wpm* pace
    (defaults to the 170 WPM shorts baseline)."""
    return round(duration_seconds / 60 * wpm)


def split_sentences(text: str) -> list[str]:
    """Split *text* into sentences on '.', '!', '?' boundaries, collapsing whitespace."""
    normalized = " ".join(text.split())
    if not normalized:
        return []
    parts = _SENTENCE_SPLIT_RE.split(normalized)
    return [p.strip() for p in parts if p.strip()]


_SCRIPT_INSTRUCTIONS_TEMPLATE = (
    "You are writing narration for a short-form vertical video (like a YouTube Short "
    "or Instagram Reel) about: {topic}\n\n"
    "STRUCTURE (mandatory):\n"
    "1. Cold-open hook as the very first sentence — a surprising statistic, a "
    "provocative question, or a bold claim. NEVER start with phrases like "
    "'In this video' or 'Today we're going to talk about'.\n"
    "2. Then 2-3 rapid, escalating facts that build on each other.\n"
    "3. A payoff last line that loops back to the hook.\n\n"
    "OUTPUT FORMAT (mandatory):\n"
    "- Plain spoken text only. No markdown, no asterisks, no headers, no bullet "
    "points, no emojis, no quotation marks around the whole thing.\n"
    "- Write numbers the way they should be SPOKEN, e.g. 'ninety percent' not '90%', "
    "'three point five million' not '3.5 million'.\n"
    "- Short sentences. Use punctuation for spoken pacing.\n"
    "- Target length: approximately {target_words} words.\n\n"
    "Write only the narration text — nothing else."
)

_QUERY_OVERRIDE_TEMPLATE = (
    "{script}\n\n"
    "---\n"
    "IGNORE the 'logical scenes' framing in the instructions above. Instead, split "
    "the script above into its individual sentences, in the exact order they appear, "
    "with no merging, omission, or paraphrasing. For each sentence:\n"
    "- 'narration' must be the sentence exactly as written above.\n"
    "- 'title' must be a concrete 2-5 word visual search query describing stock "
    "footage that would visually match that sentence (e.g. 'aerial city night', "
    "'close-up hands typing'). No abstract or vague terms.\n"
    "Return one entry per sentence, in order."
)


@dataclass(frozen=True)
class ShortsScript:
    text: str
    sentences: list[str]
    visual_queries: list[str]


def _fallback_queries(topic: str, count: int) -> list[str]:
    return [topic] * count


def _extract_queries_via_llm(
    llm: LLMProvider, script: str, sentence_count: int
) -> list[str] | None:
    """Ask the LLM (via break_into_scenes, repurposed for structured JSON output) for
    a per-sentence visual query. Returns a list aligned to *sentence_count*, or None
    if the response could not be parsed into exactly that many entries."""
    try:
        raw = llm.break_into_scenes(_QUERY_OVERRIDE_TEMPLATE.format(script=script))
    except Exception as exc:
        _log.warning("Shorts visual-query extraction call failed: %s", exc)
        return None
    queries = [str(item.get("title", "")).strip() for item in raw if isinstance(item, dict)]
    queries = [q for q in queries if q]
    if len(queries) != sentence_count:
        _log.warning(
            "Shorts visual-query extraction count mismatch: got %d, expected %d",
            len(queries), sentence_count,
        )
        return None
    return queries


def generate_shorts_script(
    topic: str,
    duration_seconds: int,
    llm: LLMProvider,
    tts_provider: str = "",
    tts_voice: str = "",
) -> ShortsScript:
    """Generate a TTS-safe shorts script and per-sentence visual queries for *topic*.

    Word target uses the stored calibration WPM for *tts_provider*+*tts_voice*
    when one exists (see shorts_tts_calibration), falling back to the 170 WPM
    default — the configured TTS voice may speak markedly slower/faster than
    that default, and using its measured pace keeps the synthesized audio
    close to *duration_seconds*.
    """
    wpm = get_wpm(tts_provider, tts_voice, default=SHORTS_WPM)
    target_words = target_word_count(duration_seconds, wpm=wpm)
    _log.info(
        "Shorts word target: %d words for %ds at %.1f WPM (provider=%s voice=%s)",
        target_words, duration_seconds, wpm, tts_provider or "?", tts_voice or "?",
    )
    prompt = _SCRIPT_INSTRUCTIONS_TEMPLATE.format(topic=topic, target_words=target_words)
    text = llm.generate_script(topic=prompt, target_words=target_words).strip()

    sentences = split_sentences(text)
    if not sentences:
        return ShortsScript(text=text, sentences=[], visual_queries=[])

    queries = _extract_queries_via_llm(llm, text, len(sentences))
    if queries is None:
        _log.info("Shorts visual-query extraction failed, retrying once")
        queries = _extract_queries_via_llm(llm, text, len(sentences))
    if queries is None:
        _log.warning(
            "Shorts visual-query extraction failed twice, falling back to topic-level query"
        )
        queries = _fallback_queries(topic, len(sentences))

    return ShortsScript(text=text, sentences=sentences, visual_queries=queries)
