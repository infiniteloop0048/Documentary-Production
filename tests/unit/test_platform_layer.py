"""Unit tests for platform_layer — covers all OS-conditional branches."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import docu_studio.platform_layer as pl


class TestConfigDir:
    def test_returns_path_instance(self) -> None:
        result = pl.config_dir()
        assert isinstance(result, Path)

    def test_contains_docu_studio(self) -> None:
        result = pl.config_dir()
        assert "docu_studio" in str(result)


class TestFfmpegExe:
    def test_returns_string(self) -> None:
        mock_ff = MagicMock()
        mock_ff.get_ffmpeg_exe.return_value = "/usr/bin/ffmpeg"
        with patch.dict("sys.modules", {"imageio_ffmpeg": mock_ff}):
            result = pl.ffmpeg_exe()
        assert result == "/usr/bin/ffmpeg"


class TestFfprobeExe:
    def test_linux_returns_ffprobe_sibling(self) -> None:
        fake_ffmpeg = "/usr/local/bin/ffmpeg"
        mock_ff = MagicMock()
        mock_ff.get_ffmpeg_exe.return_value = fake_ffmpeg
        with patch.dict("sys.modules", {"imageio_ffmpeg": mock_ff}), \
             patch("docu_studio.platform_layer.platform.system", return_value="Linux"):
            result = pl.ffprobe_exe()
        assert result == "/usr/local/bin/ffprobe"

    def test_windows_returns_ffprobe_exe(self) -> None:
        fake_ffmpeg = r"C:\tools\ffmpeg.exe"
        mock_ff = MagicMock()
        mock_ff.get_ffmpeg_exe.return_value = fake_ffmpeg
        with patch.dict("sys.modules", {"imageio_ffmpeg": mock_ff}), \
             patch("docu_studio.platform_layer.platform.system", return_value="Windows"):
            result = pl.ffprobe_exe()
        assert result.endswith("ffprobe.exe")

    def test_macos_returns_ffprobe_sibling(self) -> None:
        fake_ffmpeg = "/opt/homebrew/bin/ffmpeg"
        mock_ff = MagicMock()
        mock_ff.get_ffmpeg_exe.return_value = fake_ffmpeg
        with patch.dict("sys.modules", {"imageio_ffmpeg": mock_ff}), \
             patch("docu_studio.platform_layer.platform.system", return_value="Darwin"):
            result = pl.ffprobe_exe()
        assert result == "/opt/homebrew/bin/ffprobe"


class TestOpenFolder:
    def test_windows_calls_os_startfile(self, tmp_path: Path) -> None:
        with patch("docu_studio.platform_layer.platform.system", return_value="Windows"), \
             patch("docu_studio.platform_layer.os.startfile", create=True) as mock_sf:
            pl.open_folder(tmp_path)
        mock_sf.assert_called_once_with(str(tmp_path))

    def test_macos_calls_open(self, tmp_path: Path) -> None:
        with patch("docu_studio.platform_layer.platform.system", return_value="Darwin"), \
             patch("docu_studio.platform_layer.subprocess.call") as mock_call:
            pl.open_folder(tmp_path)
        mock_call.assert_called_once_with(["open", str(tmp_path)])

    def test_linux_calls_xdg_open(self, tmp_path: Path) -> None:
        with patch("docu_studio.platform_layer.platform.system", return_value="Linux"), \
             patch("docu_studio.platform_layer.subprocess.call") as mock_call:
            pl.open_folder(tmp_path)
        mock_call.assert_called_once_with(["xdg-open", str(tmp_path)])
