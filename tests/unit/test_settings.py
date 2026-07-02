"""Unit tests for Settings persistence and keyring helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from docu_studio.config.settings import Settings


class TestSettingsDefaults:
    def test_default_wpm(self) -> None:
        s = Settings()
        assert s.wpm == 150

    def test_default_tts_provider(self) -> None:
        s = Settings()
        assert s.tts_provider == "edge_tts"

    def test_default_output_folder_is_none(self) -> None:
        s = Settings()
        assert s.output_folder is None


class TestSettingsPersistence:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        s = Settings(wpm=120, tts_provider="elevenlabs", output_folder="/tmp/out")
        with patch("docu_studio.config.settings.config_dir", return_value=tmp_path):
            s.save()
            loaded = Settings.load()
        assert loaded.wpm == 120
        assert loaded.tts_provider == "elevenlabs"
        assert loaded.output_folder == "/tmp/out"

    def test_load_returns_defaults_when_no_file(self, tmp_path: Path) -> None:
        with patch("docu_studio.config.settings.config_dir", return_value=tmp_path):
            loaded = Settings.load()
        assert loaded.wpm == 150

    def test_load_returns_defaults_on_corrupt_file(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not json", encoding="utf-8")
        with patch("docu_studio.config.settings.config_dir", return_value=tmp_path):
            loaded = Settings.load()
        assert loaded.wpm == 150

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        s = Settings()
        with patch("docu_studio.config.settings.config_dir", return_value=nested):
            s.save()
        assert (nested / "settings.json").exists()


class TestSettingsKeyring:
    def test_get_key_returns_empty_string_when_not_set(self) -> None:
        with patch("docu_studio.config.settings.keyring.get_password", return_value=None):
            result = Settings.get_key("anthropic")
        assert result == ""

    def test_get_key_returns_stored_value(self) -> None:
        with patch("docu_studio.config.settings.keyring.get_password", return_value="sk-abc"):
            result = Settings.get_key("anthropic")
        assert result == "sk-abc"

    def test_set_key_calls_keyring(self) -> None:
        with patch("docu_studio.config.settings.keyring.set_password") as mock_set:
            Settings.set_key("anthropic", "sk-xyz")
        mock_set.assert_called_once_with("docu_studio", "anthropic", "sk-xyz")
