"""Anthropic Claude adapter — implements LLMProvider using the anthropic SDK."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

import anthropic

from docu_studio.adapters.llm.base import _SCRIPT_CHUNK_TOLERANCE, LLMProvider
from docu_studio.pipeline.events import LogEvent, sanitize_log_message
from docu_studio.retry import retry

_logger = logging.getLogger(__name__)


class AnthropicAdapter(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5") -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate_script(
        self,
        topic: str,
        target_words: int,
        on_diminishing_returns: Callable[[int], None] | None = None,
    ) -> str:
        def _generate_chunk(script_so_far: str, words_needed: int) -> str:
            # ~1.4 tokens/word for English prose, plus a buffer so max_tokens itself
            # never truncates a chunk before the model finishes it.
            max_tokens = min(8192, max(1024, int(words_needed * 1.6) + 256))
            if not script_so_far:
                prompt = (
                    f"Write a documentary narration script about '{topic}'. "
                    f"Target length: {target_words} words — stay within "
                    f"{target_words} to {int(target_words * 1.1)} words, do not go "
                    "meaningfully under or over. Write only the script, no headings "
                    "or commentary."
                )
            else:
                prompt = (
                    f"Continue the documentary narration script below about '{topic}'. "
                    f"Write {words_needed} more words to reach the {target_words}-word "
                    "target — stay close to this amount, do not go meaningfully under "
                    "or over. Continue directly from where it left off — do not repeat "
                    f"prior content, do not add headings or "
                    f"commentary.\n\n--- Script so far ---\n{script_so_far}"
                )
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text  # type: ignore[union-attr]

        script = self._generate_script_in_chunks(
            target_words, _generate_chunk, on_diminishing_returns=on_diminishing_returns
        )
        actual_words = len(script.split())
        if target_words and actual_words < target_words * (1 - _SCRIPT_CHUNK_TOLERANCE):
            _logger.warning(
                "generate_script: word count target missed after chunked generation — "
                "target=%d actual=%d (%.0f%% of target)",
                target_words, actual_words,
                100 * actual_words / target_words,
            )
        return script

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def break_into_scenes(self, script: str) -> list[dict]:
        tools = [
            {
                "name": "scene_list",
                "description": "Return the script broken into scenes.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scenes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "narration": {"type": "string"},
                                },
                                "required": ["title", "narration"],
                            },
                        }
                    },
                    "required": ["scenes"],
                },
            }
        ]
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            tools=tools,  # type: ignore[arg-type]
            tool_choice={"type": "tool", "name": "scene_list"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Break the following documentary script into logical scenes. "
                        "Each scene needs a short title and its narration text.\n\n"
                        + script
                    ),
                }
            ],
        )
        for block in msg.content:
            if block.type == "tool_use" and block.name == "scene_list":
                return block.input["scenes"]  # type: ignore[index]
        return []

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def extract_visual_keywords(self, title: str, narration: str) -> list[str]:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Given this scene narration, return ONLY a comma-separated list of "
                        "3-6 visual search keywords. No JSON, no markdown, no explanation, "
                        f"no numbering. Just keywords separated by commas.\n\nNarration: {narration}"
                    ),
                }
            ],
        )
        raw = msg.content[0].text.strip() if msg.content else ""  # type: ignore[union-attr]
        keywords = [k.strip() for k in raw.split(",") if k.strip()]
        if not keywords and raw:
            _logger.warning("Keyword parse failed, raw response: %s", raw[:200])
        return keywords

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def suggest_topic(self) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=128,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Suggest one compelling documentary topic that is currently trending "
                        "and would make great video content. Reply with only the topic title, "
                        "no explanation."
                    ),
                }
            ],
        )
        return msg.content[0].text.strip()  # type: ignore[union-attr]
