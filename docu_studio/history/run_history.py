"""Persistent run history stored as a JSON file in the OS config directory."""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from docu_studio.platform_layer import config_dir

_HISTORY_FILE = "run_history.json"
_MAX_RECORDS = 100

TopicSource = Literal["web_search", "ai_suggested", "user_supplied"]


@dataclass
class RunRecord:
    topic: str
    mode: str
    status: str
    started_at: datetime
    project_folder: Path
    topic_source: TopicSource = "user_supplied"
    fallback_triggered: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        d["project_folder"] = str(self.project_folder)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        return cls(
            topic=d["topic"],
            mode=d["mode"],
            status=d["status"],
            started_at=datetime.fromisoformat(d["started_at"]),
            project_folder=Path(d["project_folder"]),
            topic_source=d.get("topic_source", "user_supplied"),
            fallback_triggered=d.get("fallback_triggered", False),
        )


def _history_path() -> Path:
    return config_dir() / _HISTORY_FILE


def load_history() -> list[RunRecord]:
    path = _history_path()
    if not path.exists():
        return []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        return [RunRecord.from_dict(r) for r in records]
    except Exception:
        return []


def save_run(run: RunRecord) -> None:
    """Append *run* to history (atomic write) and prune to the last 100 records."""
    records = load_history()
    records.append(run)
    records = records[-_MAX_RECORDS:]
    data = json.dumps([r.to_dict() for r in records], indent=2)

    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write via temp file + rename
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
