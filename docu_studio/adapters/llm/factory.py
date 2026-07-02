"""Factory for LLM adapters."""
from __future__ import annotations

from docu_studio.adapters.llm.base import LLMProvider


def build_llm(provider: str, api_key: str, model: str) -> LLMProvider:
    p = provider.lower()
    if p == "openai":
        from docu_studio.adapters.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(api_key=api_key, model=model)
    if p == "openrouter":
        from docu_studio.adapters.llm.openrouter_adapter import OpenRouterAdapter
        return OpenRouterAdapter(api_key=api_key, model=model)
    if p == "groq":
        from docu_studio.adapters.llm.groq_adapter import GroqAdapter
        return GroqAdapter(api_key=api_key, model=model)
    from docu_studio.adapters.llm.anthropic_adapter import AnthropicAdapter
    return AnthropicAdapter(api_key=api_key, model=model)
