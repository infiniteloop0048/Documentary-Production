"""OpenAI-compatible LLM adapter — covers OpenAI, OpenRouter, and Groq."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import TypeVar

from openai import OpenAI

from docu_studio.adapters.llm.base import _SCRIPT_CHUNK_TOLERANCE, LLMProvider

_logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_MAX_RETRIES = 3
_RETRY_DELAY = 3.0


def _with_retry(fn: Callable[[], _T]) -> _T:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {_MAX_RETRIES} attempts: {last_exc}") from last_exc


class _OpenAICompatBase(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self._api_key = api_key

    def generate_script(
        self,
        topic: str,
        target_words: int,
        on_diminishing_returns: Callable[[int], None] | None = None,
    ) -> str:
        def _generate_chunk(script_so_far: str, words_needed: int) -> str:
            # ~1.4 tokens/word for English prose, plus a buffer so max_tokens itself
            # never truncates a chunk before the model finishes it. The extra buffer
            # also covers reasoning models (e.g. DeepSeek) that spend part of the
            # completion budget on hidden reasoning tokens before visible content.
            max_tokens = min(8192, max(1536, int(words_needed * 1.6) + 1024))
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

            def _call() -> str:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = resp.choices[0].message.content
                if not content:
                    # A 200 response with empty content happens with reasoning models
                    # that exhaust max_tokens on hidden reasoning before writing any
                    # visible text — treat it as a failure so _with_retry retries it
                    # instead of silently producing an empty script chunk.
                    finish_reason = resp.choices[0].finish_reason
                    raise RuntimeError(
                        f"LLM returned empty completion (finish_reason={finish_reason})"
                    )
                return content
            return _with_retry(_call)

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

    def break_into_scenes(self, script: str) -> list[dict]:
        def _call() -> list[dict]:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": (
                        "Break the following documentary script into logical scenes. "
                        "Return a JSON object with a 'scenes' array where each element "
                        "has 'title' (string) and 'narration' (string) keys. "
                        "Return only valid JSON, no other text.\n\nScript:\n" + script
                    ),
                }],
            )
            raw = resp.choices[0].message.content or "{}"
            raw_text = raw.strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()
            data = json.loads(raw_text)
            if isinstance(data, dict) and "scenes" in data:
                return data["scenes"]
            if isinstance(data, list):
                return data
            return []
        return _with_retry(_call)

    def extract_visual_keywords(self, title: str, narration: str) -> list[str]:
        def _call() -> list[str]:
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": (
                        "Given this scene narration, return ONLY a comma-separated list of "
                        "3-6 visual search keywords. No JSON, no markdown, no explanation, "
                        f"no numbering. Just keywords separated by commas.\n\nNarration: {narration}"
                    ),
                }],
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()
            keywords = [k.strip() for k in raw.split(",") if k.strip()]
            if not keywords and raw:
                _logger.warning("Keyword parse failed, raw response: %s", raw[:200])
            return keywords
        return _with_retry(_call)

    def suggest_topic(self) -> str:
        def _call() -> str:
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=128,
                messages=[{
                    "role": "user",
                    "content": (
                        "Suggest one compelling documentary topic that is currently trending "
                        "and would make great video content. Reply with only the topic title, "
                        "no explanation."
                    ),
                }],
            )
            return (resp.choices[0].message.content or "").strip()
        return _with_retry(_call)


class OpenAIAdapter(_OpenAICompatBase):
    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        super().__init__(api_key=api_key, model=model)
