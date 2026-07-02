"""Unit tests for pipeline events and sanitize_log_message."""
from __future__ import annotations

import pytest

from docu_studio.pipeline.events import (
    ErrorEvent,
    LogEvent,
    LogLevel,
    ProgressEvent,
    sanitize_log_message,
)


class TestSanitizeLogMessage:
    def test_replaces_key_with_redacted(self) -> None:
        result = sanitize_log_message("API key is abc123", ["abc123"])
        assert "abc123" not in result
        assert "***REDACTED***" in result

    def test_replaces_multiple_keys(self) -> None:
        result = sanitize_log_message("keys: foo and bar", ["foo", "bar"])
        assert "foo" not in result
        assert "bar" not in result

    def test_skips_empty_key(self) -> None:
        result = sanitize_log_message("message", [""])
        assert result == "message"

    def test_returns_unchanged_when_no_match(self) -> None:
        result = sanitize_log_message("hello world", ["zzz"])
        assert result == "hello world"

    def test_empty_keys_list(self) -> None:
        result = sanitize_log_message("message", [])
        assert result == "message"


class TestEventDataclasses:
    def test_progress_event_frozen(self) -> None:
        e = ProgressEvent(stage="Test", message="msg")
        with pytest.raises((AttributeError, TypeError)):
            e.stage = "other"  # type: ignore[misc]

    def test_log_event_frozen(self) -> None:
        e = LogEvent(message="hello")
        with pytest.raises((AttributeError, TypeError)):
            e.message = "new"  # type: ignore[misc]

    def test_error_event_defaults(self) -> None:
        e = ErrorEvent(message="oops")
        assert e.fatal is True
        assert e.shortage is False

    def test_progress_event_scene_fields_default_none(self) -> None:
        e = ProgressEvent(stage="S")
        assert e.scene_index is None
        assert e.scene_total is None

    def test_log_level_default_is_info(self) -> None:
        e = LogEvent(message="msg")
        assert e.level == LogLevel.INFO
