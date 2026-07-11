"""Create and initialize per-run project output folders."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def _safe_topic(topic: str) -> str:
    """Sanitize topic string for use in a folder name."""
    return re.sub(r"[^\w\-]", "_", topic)[:40].strip("_") or "run"


def create_project_folder(topic: str, ts: datetime, base: Path) -> Path:
    """Create *{base}/{topic}_{timestamp}/* with audio/, video/ subdirs and placeholder files.

    Raises OSError if the directory cannot be created (e.g., permission denied).
    """
    folder_name = f"{_safe_topic(topic)}_{ts.strftime('%Y%m%d_%H%M%S')}"
    project_path = base / folder_name
    try:
        project_path.mkdir(parents=True, exist_ok=True)
        (project_path / "audio").mkdir(exist_ok=True)
        (project_path / "video").mkdir(exist_ok=True)
    except PermissionError as exc:
        raise OSError(
            f"Cannot create project folder at '{project_path}': permission denied."
        ) from exc

    # Placeholders — filled in by pipeline stages
    (project_path / "script.md").write_text("", encoding="utf-8")
    (project_path / "scenes.json").write_text(json.dumps([]), encoding="utf-8")

    return project_path
