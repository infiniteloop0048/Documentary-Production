"""LLM-generated narration for Slideshow — even, descriptive pacing, distinct
from docu_studio/shorts/shorts_script_gen.py's punchy hook/payoff style.
Feeds its output into Phase 1's existing script_text -> SlideshowConfig ->
TTS -> split_duration_evenly pipeline unchanged; no sentence-splitting is
needed since that pipeline's segmentation is duration-only, not per-sentence.
"""
from __future__ import annotations

from docu_studio.adapters.llm.base import LLMProvider

SLIDESHOW_WPM = 150
_DEFAULT_SECONDS_PER_IMAGE = 5.0

_SCRIPT_INSTRUCTIONS_TEMPLATE = (
    "You are writing narration for a slideshow video about: {topic}\n\n"
    "STYLE (mandatory):\n"
    "- Even, descriptive, documentary-style narration paced steadily across "
    "the whole script.\n"
    "- No cold-open hook, no rhetorical questions, no payoff/loop structure, "
    "no calls to action.\n"
    "- Plain spoken text only. No markdown, no asterisks, no headers, no "
    "bullet points, no emojis, no quotation marks around the whole thing.\n"
    "- Write numbers the way they should be spoken, e.g. 'ninety percent' "
    "not '90%'.\n"
    "- Target length: approximately {target_words} words.\n\n"
    "Write only the narration text — nothing else."
)


def target_word_count(
    image_count: int,
    seconds_per_image: float = _DEFAULT_SECONDS_PER_IMAGE,
    wpm: float = SLIDESHOW_WPM,
) -> int:
    """Return the target word count for narrating *image_count* images at
    *seconds_per_image* seconds each, spoken at *wpm* words per minute."""
    if image_count <= 0:
        raise ValueError("image_count must be positive")
    duration_seconds = image_count * seconds_per_image
    return round(duration_seconds / 60 * wpm)


def generate_slideshow_script(topic: str, image_count: int, llm: LLMProvider) -> str:
    """Generate even, descriptive slideshow narration for *topic*, sized for
    *image_count* images."""
    target_words = target_word_count(image_count)
    prompt = _SCRIPT_INSTRUCTIONS_TEMPLATE.format(topic=topic, target_words=target_words)
    return llm.generate_script(topic=prompt, target_words=target_words).strip()
