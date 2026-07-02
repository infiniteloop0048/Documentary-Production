"""Groq LLM adapter — OpenAI-compatible, ultra-fast inference."""
from __future__ import annotations

from docu_studio.adapters.llm.openai_adapter import _OpenAICompatBase


class GroqAdapter(_OpenAICompatBase):
    def __init__(self, api_key: str, model: str = "llama-3.1-70b-versatile") -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.groq.com/openai/v1",
        )
