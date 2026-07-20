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
from docu_studio.shorts.music_providers import DEFAULT_MUSIC_MOOD
from docu_studio.common.tts_calibration import get_wpm

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
    "- Target length: {target_words} to {target_words_max} words — stay within this "
    "range, do not go meaningfully under or over.\n\n"
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
    "Additionally, on the FIRST entry only, include a 'music_moods' key: an array "
    "of exactly 3 different single-word background-music mood/genre tags for this "
    "whole video, ordered from most fitting to least fitting (e.g. [\"epic\", "
    "\"cinematic\", \"dramatic\"]). Each word should be a term commonly used to tag "
    "instrumental background music. Omit this key on every other entry.\n"
    "Return one entry per sentence, in order."
)

_STYLE_GUIDE_TEMPLATE = (
    "Here is a video narration script:\n\n{script}\n\n"
    "---\n"
    "Write a short VISUAL STYLE GUIDE (120-180 words) for illustrating this script as a "
    "sequence of AI-generated images that must look like one consistent, cohesive story. "
    "Cover, in prose:\n"
    "1. Art style/medium (e.g. cinematic photography, watercolor illustration, 3D render) "
    "and overall color palette/mood.\n"
    "2. The main recurring subject(s) — if the script follows a person, character, place, "
    "or object across multiple scenes, describe their fixed appearance in specific, concrete "
    "visual terms (age, build, clothing, materials, colors) so it can be repeated identically "
    "in every scene. If the script has no single recurring subject (e.g. it covers many "
    "different facts/places), say so explicitly instead of inventing one.\n"
    "3. The recurring setting/era/environment, if any.\n\n"
    "Write only the style guide text — nothing else, no headers, no markdown."
)

_QUERY_OVERRIDE_TEMPLATE_AI_IMAGE = (
    "{script}\n\n"
    "---\n"
    "IGNORE the 'logical scenes' framing in the instructions above. Instead, split "
    "the script above into its individual sentences, in the exact order they appear, "
    "with no merging, omission, or paraphrasing. For each sentence:\n"
    "- 'narration' must be the sentence exactly as written above.\n"
    "- 'title' must be a concrete 2-5 word visual search query describing stock "
    "footage that would visually match that sentence (e.g. 'aerial city night', "
    "'close-up hands typing'). No abstract or vague terms.\n"
    "- 'image_prompt' must be a detailed, concrete prompt (40-80 words) for an AI "
    "image-generation model to illustrate that exact sentence: specify the subject, "
    "specific action/pose, setting, camera framing/shot type (e.g. wide establishing "
    "shot, close-up, over-the-shoulder), lighting, and mood. Be precise and visual, "
    "not abstract — describe exactly what should be seen in frame.\n"
    "Additionally, on the FIRST entry only, include a 'music_moods' key: an array "
    "of exactly 3 different single-word background-music mood/genre tags for this "
    "whole video, ordered from most fitting to least fitting (e.g. [\"epic\", "
    "\"cinematic\", \"dramatic\"]). Each word should be a term commonly used to tag "
    "instrumental background music. Omit this key on every other entry.\n"
    "Return one entry per sentence, in order."
)

_QUERY_OVERRIDE_TEMPLATE_AI_IMAGE_STORY = (
    "{script}\n\n"
    "---\n"
    "VISUAL STYLE GUIDE for this video (every image must follow this consistently):\n"
    "{style_guide}\n"
    "---\n"
    "IGNORE the 'logical scenes' framing in the instructions above. Instead, split "
    "the script above into its individual sentences, in the exact order they appear, "
    "with no merging, omission, or paraphrasing. For each sentence:\n"
    "- 'narration' must be the sentence exactly as written above.\n"
    "- 'title' must be a concrete 2-5 word visual search query describing stock "
    "footage that would visually match that sentence (e.g. 'aerial city night', "
    "'close-up hands typing'). No abstract or vague terms.\n"
    "- 'image_prompt' must be a detailed, concrete prompt (50-100 words) for an AI "
    "image-generation model to illustrate that exact sentence, and MUST open by "
    "restating the style guide's art style and recurring subject/setting description "
    "above (in your own words, consistently across every entry), then add this "
    "sentence's specific action, camera framing/shot type, lighting, and mood. Be "
    "precise and visual, not abstract.\n"
    "Additionally, on the FIRST entry only, include a 'music_moods' key: an array "
    "of exactly 3 different single-word background-music mood/genre tags for this "
    "whole video, ordered from most fitting to least fitting (e.g. [\"epic\", "
    "\"cinematic\", \"dramatic\"]). Each word should be a term commonly used to tag "
    "instrumental background music. Omit this key on every other entry.\n"
    "Return one entry per sentence, in order."
)


@dataclass(frozen=True)
class ShortsScript:
    text: str
    sentences: list[str]
    visual_queries: list[str]
    music_moods: tuple[str, ...] = (DEFAULT_MUSIC_MOOD,)
    image_prompts: tuple[str, ...] = ()


def _fallback_queries(topic: str, count: int) -> list[str]:
    return [topic] * count


# LLM word-count instructions are advisory, not enforced — reasoning models in
# particular have been observed overshooting a small target by 2x+ even with
# bounded-range wording. Shorts duration is driven directly by narration word
# count downstream (TTS audio length -> footage assembly), so an unchecked
# overshoot silently produces a much longer video than requested. Trim as a
# hard safety net rather than relying on prompt compliance alone.
_OVERSHOOT_TRIM_THRESHOLD = 1.15


def _trim_to_word_budget(text: str, target_words: int) -> str:
    """Trim *text* to approximately *target_words*, cutting only at sentence
    boundaries so the result stays well-formed for TTS."""
    sentences = split_sentences(text)
    if not sentences:
        return text
    kept: list[str] = []
    words_so_far = 0
    for sentence in sentences:
        kept.append(sentence)
        words_so_far += len(sentence.split())
        if words_so_far >= target_words:
            break
    return " ".join(kept)


def _fetch_scene_json(llm: LLMProvider, prompt: str) -> list[dict] | None:
    """Make the single break_into_scenes call shared by query/mood/image-prompt
    extraction. *prompt* is the already-formatted instruction string (the
    query, AI-image, or AI-image-story template applied to the script)."""
    try:
        raw = llm.break_into_scenes(prompt)
    except Exception as exc:
        _log.warning("Shorts visual-query extraction call failed: %s", exc)
        return None
    return raw if isinstance(raw, list) else None


def _queries_from_raw(raw: list[dict] | None, sentence_count: int) -> list[str] | None:
    """Parse the per-sentence visual query out of an already-fetched *raw* response.
    Returns a list aligned to *sentence_count*, or None if it couldn't be parsed
    into exactly that many entries."""
    if raw is None:
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


_MUSIC_MOODS_MAX = 3


def _moods_from_raw(raw: list[dict] | None) -> tuple[str, ...]:
    """Return up to 3 valid single-word music mood/genre tags (most-fitting first)
    from an already-fetched *raw* response, or a single-element default tuple if
    absent, malformed, or empty after validation. Multiple tags let the caller
    try Jamendo with fallback tags — a single mood word sometimes has zero
    matching tracks, silently producing a musicless video."""
    if not raw:
        return (DEFAULT_MUSIC_MOOD,)
    for item in raw:
        if not isinstance(item, dict):
            continue
        raw_moods = item.get("music_moods")
        if not isinstance(raw_moods, list):
            continue
        moods: list[str] = []
        for candidate in raw_moods:
            word = str(candidate).strip().lower()
            if word and " " not in word and word not in moods:
                moods.append(word)
            if len(moods) == _MUSIC_MOODS_MAX:
                break
        if moods:
            return tuple(moods)
    return (DEFAULT_MUSIC_MOOD,)


def _generate_style_guide(llm: LLMProvider, script_text: str) -> str:
    """One-shot call producing a reusable visual style/character/setting
    description, folded into every per-sentence image_prompt so AI-generated
    scenes read as one consistent story rather than disconnected images.
    Returns "" on failure — caller degrades to independent per-sentence
    prompts rather than failing the whole run over an optional call."""
    prompt = _STYLE_GUIDE_TEMPLATE.format(script=script_text)
    try:
        return llm.generate_script(topic=prompt, target_words=150).strip()
    except Exception as exc:
        _log.warning("Shorts style-guide generation failed: %s", exc)
        return ""


def _image_prompts_from_raw(raw: list[dict] | None, sentence_count: int) -> list[str] | None:
    """Parse the per-sentence AI image_prompt out of an already-fetched *raw*
    response. Returns a list aligned to *sentence_count*, or None if it
    couldn't be parsed into exactly that many non-empty entries."""
    if raw is None:
        return None
    prompts = [str(item.get("image_prompt", "")).strip() for item in raw if isinstance(item, dict)]
    prompts = [p for p in prompts if p]
    if len(prompts) != sentence_count:
        _log.warning(
            "Shorts image-prompt extraction count mismatch: got %d, expected %d",
            len(prompts), sentence_count,
        )
        return None
    return prompts


def generate_shorts_script(
    topic: str,
    duration_seconds: int,
    llm: LLMProvider,
    tts_provider: str = "",
    tts_voice: str = "",
    footage_source: str = "video",
    story_continuity: bool = True,
) -> ShortsScript:
    """Generate a TTS-safe shorts script and per-sentence visual queries for *topic*.

    Word target uses the stored calibration WPM for *tts_provider*+*tts_voice*
    when one exists (see docu_studio.common.tts_calibration), falling back to the 170 WPM
    default — the configured TTS voice may speak markedly slower/faster than
    that default, and using its measured pace keeps the synthesized audio
    close to *duration_seconds*.

    When *footage_source* is "ai_image", each sentence also gets a detailed
    'image_prompt' for AI image generation (ShortsScript.image_prompts). If
    *story_continuity* is also True, one extra LLM call first produces a
    reusable visual style guide (art style, recurring subject/setting) that's
    folded into every image_prompt so generated scenes read as one coherent
    story; if False, each image_prompt is generated independently per
    sentence with no shared style guide. For any other footage_source,
    image_prompts stays empty and behavior is unchanged from before.
    """
    wpm = get_wpm(tts_provider, tts_voice, default=SHORTS_WPM)
    target_words = target_word_count(duration_seconds, wpm=wpm)
    _log.info(
        "Shorts word target: %d words for %ds at %.1f WPM (provider=%s voice=%s)",
        target_words, duration_seconds, wpm, tts_provider or "?", tts_voice or "?",
    )
    prompt = _SCRIPT_INSTRUCTIONS_TEMPLATE.format(
        topic=topic, target_words=target_words,
        target_words_max=int(target_words * _OVERSHOOT_TRIM_THRESHOLD),
    )
    text = llm.generate_script(topic=prompt, target_words=target_words).strip()

    actual_words = len(text.split())
    if actual_words > target_words * _OVERSHOOT_TRIM_THRESHOLD:
        trimmed = _trim_to_word_budget(text, target_words)
        _log.warning(
            "Shorts script overshot word target (%d words for a %d-word target, "
            "%.0f%%) — trimmed to %d words to keep video duration close to requested.",
            actual_words, target_words, 100 * actual_words / target_words,
            len(trimmed.split()),
        )
        text = trimmed

    sentences = split_sentences(text)
    if not sentences:
        return ShortsScript(text=text, sentences=[], visual_queries=[])

    ai_image_mode = footage_source == "ai_image"
    style_guide = _generate_style_guide(llm, text) if (ai_image_mode and story_continuity) else ""

    def _scene_prompt() -> str:
        if not ai_image_mode:
            return _QUERY_OVERRIDE_TEMPLATE.format(script=text)
        if style_guide:
            return _QUERY_OVERRIDE_TEMPLATE_AI_IMAGE_STORY.format(script=text, style_guide=style_guide)
        return _QUERY_OVERRIDE_TEMPLATE_AI_IMAGE.format(script=text)

    raw = _fetch_scene_json(llm, _scene_prompt())
    queries = _queries_from_raw(raw, len(sentences))
    music_moods = _moods_from_raw(raw)
    image_prompts = _image_prompts_from_raw(raw, len(sentences)) if ai_image_mode else None
    if queries is None or (ai_image_mode and image_prompts is None):
        _log.info("Shorts visual-query extraction failed, retrying once")
        raw = _fetch_scene_json(llm, _scene_prompt())
        queries = _queries_from_raw(raw, len(sentences))
        if music_moods == (DEFAULT_MUSIC_MOOD,):
            music_moods = _moods_from_raw(raw)
        if ai_image_mode:
            image_prompts = _image_prompts_from_raw(raw, len(sentences))
    if queries is None:
        _log.warning(
            "Shorts visual-query extraction failed twice, falling back to topic-level query"
        )
        queries = _fallback_queries(topic, len(sentences))
    if ai_image_mode and image_prompts is None:
        _log.warning(
            "Shorts AI image-prompt extraction failed twice, falling back to visual queries as prompts"
        )
        image_prompts = list(queries)

    return ShortsScript(
        text=text, sentences=sentences, visual_queries=queries,
        music_moods=music_moods,
        image_prompts=tuple(image_prompts) if ai_image_mode else (),
    )
