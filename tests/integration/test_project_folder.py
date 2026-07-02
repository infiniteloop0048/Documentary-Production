"""Integration test: output folder not writable raises OSError with human-readable message."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from docu_studio.output.project_folder import create_project_folder


class TestCreateProjectFolder:
    def test_creates_folder_with_audio_video_subdirs(self, tmp_path: Path) -> None:
        ts = datetime(2026, 6, 22, 10, 0, 0)
        folder = create_project_folder("Apollo 11", ts, tmp_path)
        assert folder.exists()
        assert (folder / "audio").is_dir()
        assert (folder / "video").is_dir()
        assert (folder / "script.md").exists()
        assert (folder / "scenes.json").exists()

    def test_raises_oserror_on_permission_denied(self, tmp_path: Path) -> None:
        ts = datetime(2026, 6, 22, 10, 0, 0)
        with patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
            with pytest.raises(OSError) as exc_info:
                create_project_folder("Test Topic", ts, tmp_path)
        msg = str(exc_info.value)
        assert "permission denied" in msg.lower()

    def test_error_message_contains_no_api_keys(self, tmp_path: Path) -> None:
        ts = datetime(2026, 6, 22, 10, 0, 0)
        with patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
            with pytest.raises(OSError) as exc_info:
                create_project_folder("Topic", ts, tmp_path)
        assert "sk-" not in str(exc_info.value)
        assert "Bearer" not in str(exc_info.value)
