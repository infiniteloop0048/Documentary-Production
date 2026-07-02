"""OpenRouter LLM adapter — OpenAI-compatible, routes to many providers."""
from __future__ import annotations

from docu_studio.adapters.llm.openai_adapter import _OpenAICompatBase


class OpenRouterAdapter(_OpenAICompatBase):
    def __init__(self, api_key: str, model: str = "openai/gpt-4o") -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://openrouter.ai/api/v1",
        )
