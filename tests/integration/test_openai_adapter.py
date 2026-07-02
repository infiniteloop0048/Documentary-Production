"""Integration tests for _OpenAICompatBase.generate_script (shared by OpenAI/Groq/OpenRouter).

Covers the same chunked-generation fix as AnthropicAdapter (see test_anthropic_adapter.py):
a single short completion must not be silently accepted when it falls short of the
requested word-count target.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from docu_studio.adapters.llm.openai_adapter import OpenAIAdapter


def _make_adapter() -> tuple[OpenAIAdapter, MagicMock]:
    mock_client = MagicMock()
    with patch("docu_studio.adapters.llm.openai_adapter.OpenAI", return_value=mock_client):
        adapter = OpenAIAdapter(api_key="test-key")
    return adapter, mock_client


def _completion(text: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    return resp


class TestGenerateScript:
    def test_returns_string(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.chat.completions.create.return_value = _completion("word " * 900)
        result = adapter.generate_script("Topic", 900)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_max_tokens_scales_above_default_for_long_targets(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.chat.completions.create.return_value = _completion("word " * 4500)
        adapter.generate_script("Topic", 4500)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] > 4096

    def test_continues_generating_when_first_chunk_falls_short_of_target(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.chat.completions.create.side_effect = [
            _completion("word " * 1100),
            _completion("word " * 3500),
        ]
        result = adapter.generate_script("Topic", 4500)
        assert mock_client.chat.completions.create.call_count == 2
        assert len(result.split()) >= 4500 * 0.9

    def test_stops_chunking_once_target_reached(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.chat.completions.create.return_value = _completion("word " * 1000)
        adapter.generate_script("Topic", 900)
        assert mock_client.chat.completions.create.call_count == 1

    def test_calls_on_diminishing_returns_when_chunk_contribution_plateaus(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.chat.completions.create.side_effect = [
            _completion("word " * 1100),
            _completion("word " * 50),  # tiny continuation — plateau signal
        ]
        triggered: list[int] = []
        adapter.generate_script("Topic", 4500, on_diminishing_returns=triggered.append)
        assert triggered, "expected on_diminishing_returns to fire for a plateaued chunk"
        assert mock_client.chat.completions.create.call_count == 2
