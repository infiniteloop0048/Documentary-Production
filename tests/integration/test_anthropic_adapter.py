"""T039: HTTP-mocked integration tests for AnthropicAdapter."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.llm.anthropic_adapter import AnthropicAdapter
from docu_studio.config.settings import Settings


def _make_settings(api_key: str = "test-key") -> Settings:
    s = Settings()
    with patch.object(Settings, "get_key", return_value=api_key):
        return s


def _make_adapter() -> tuple[AnthropicAdapter, MagicMock]:
    settings = Settings()
    mock_client = MagicMock()
    with patch("docu_studio.adapters.llm.anthropic_adapter.anthropic.Anthropic", return_value=mock_client), \
         patch.object(Settings, "get_key", return_value="test-key"):
        adapter = AnthropicAdapter(settings)
    return adapter, mock_client


class TestGenerateScript:
    def test_returns_string(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="This is the script.")]
        )
        result = adapter.generate_script("Apollo 11", 3000)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_calls_create_with_correct_model(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Script text.")]
        )
        adapter.generate_script("Topic", 1000)
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "claude" in call_kwargs["model"]

    def test_max_tokens_scales_above_default_for_long_targets(self) -> None:
        """Regression test: a fixed max_tokens=4096 cap truncates long scripts —
        4500 words is ~6000-7000 tokens, well past the old hardcoded cap."""
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="word " * 4500)]
        )
        adapter.generate_script("Topic", 4500)
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] > 4096

    def test_continues_generating_when_first_chunk_falls_short_of_target(self) -> None:
        """Reproduces the bug: a single short completion (~1100 words) should not be
        accepted as final when the target is 4500 words — the adapter must ask the
        model to continue until the target is reached (within tolerance)."""
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.side_effect = [
            MagicMock(content=[MagicMock(text="word " * 1100)]),
            MagicMock(content=[MagicMock(text="word " * 3500)]),
        ]
        result = adapter.generate_script("Topic", 4500)
        assert mock_client.messages.create.call_count == 2
        assert len(result.split()) >= 4500 * 0.9

    def test_stops_chunking_once_target_reached(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="word " * 1000)]
        )
        adapter.generate_script("Topic", 900)
        assert mock_client.messages.create.call_count == 1

    def test_calls_on_diminishing_returns_when_chunk_contribution_plateaus(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.side_effect = [
            MagicMock(content=[MagicMock(text="word " * 1100)]),
            MagicMock(content=[MagicMock(text="word " * 50)]),  # tiny continuation — plateau
        ]
        triggered: list[int] = []
        adapter.generate_script("Topic", 4500, on_diminishing_returns=triggered.append)
        assert triggered, "expected on_diminishing_returns to fire for a plateaued chunk"
        assert mock_client.messages.create.call_count == 2


class TestBreakIntoScenes:
    def _tool_response(self, scenes: list[dict]) -> MagicMock:
        msg = MagicMock()
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "scene_list"
        tool_block.input = {"scenes": scenes}
        msg.content = [tool_block]
        return msg

    def test_returns_list_of_dicts(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = self._tool_response([
            {"title": "Scene 1", "narration": "Narration 1"},
            {"title": "Scene 2", "narration": "Narration 2"},
        ])
        result = adapter.break_into_scenes("script text")
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(s, dict) for s in result)

    def test_scene_dicts_have_title_and_narration(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = self._tool_response([
            {"title": "Opening", "narration": "The rocket launched."},
        ])
        result = adapter.break_into_scenes("script")
        assert "title" in result[0]
        assert "narration" in result[0]


class TestExtractVisualKeywords:
    def _tool_response(self, keywords: list[str]) -> MagicMock:
        msg = MagicMock()
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "keywords"
        tool_block.input = {"keywords": keywords}
        msg.content = [tool_block]
        return msg

    def test_returns_list_of_strings(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = self._tool_response(
            ["rocket launch", "astronaut", "moon surface"]
        )
        result = adapter.extract_visual_keywords("Moon Landing", "Astronauts landed.")
        assert isinstance(result, list)
        assert all(isinstance(k, str) for k in result)

    def test_returns_expected_keywords(self) -> None:
        adapter, mock_client = _make_adapter()
        mock_client.messages.create.return_value = self._tool_response(["space", "rocket"])
        result = adapter.extract_visual_keywords("Title", "Narration")
        assert "space" in result
        assert "rocket" in result
