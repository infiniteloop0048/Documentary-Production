"""Unit tests for run_history module."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from docu_studio.history.run_history import RunRecord, load_history, save_run


def _sample_record(tmp_path: Path, *, status: str = "completed") -> RunRecord:
    return RunRecord(
        topic="Apollo 11",
        mode="guided",
        status=status,
        started_at=datetime(2026, 1, 1, 12, 0, 0),
        project_folder=tmp_path / "runs" / "apollo",
        topic_source="user_supplied",
        fallback_triggered=False,
    )


class TestRunRecord:
    def test_to_dict_round_trip(self, tmp_path: Path) -> None:
        record = _sample_record(tmp_path)
        d = record.to_dict()
        restored = RunRecord.from_dict(d)
        assert restored.topic == record.topic
        assert restored.mode == record.mode
        assert restored.status == record.status
        assert restored.started_at == record.started_at
        assert restored.project_folder == record.project_folder

    def test_to_dict_serializes_datetime_as_string(self, tmp_path: Path) -> None:
        record = _sample_record(tmp_path)
        d = record.to_dict()
        assert isinstance(d["started_at"], str)

    def test_from_dict_defaults(self) -> None:
        minimal = {
            "topic": "T",
            "mode": "guided",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00",
            "project_folder": "/tmp/proj",
        }
        record = RunRecord.from_dict(minimal)
        assert record.topic_source == "user_supplied"
        assert record.fallback_triggered is False


class TestLoadHistory:
    def test_returns_empty_list_when_no_file(self, tmp_path: Path) -> None:
        with patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            result = load_history()
        assert result == []

    def test_returns_saved_records(self, tmp_path: Path) -> None:
        record = _sample_record(tmp_path)
        with patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            save_run(record)
            history = load_history()
        assert len(history) == 1
        assert history[0].topic == "Apollo 11"

    def test_returns_empty_on_corrupt_file(self, tmp_path: Path) -> None:
        history_file = tmp_path / "run_history.json"
        history_file.write_text("not valid json", encoding="utf-8")
        with patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            result = load_history()
        assert result == []


class TestSaveRun:
    def test_appends_record(self, tmp_path: Path) -> None:
        r1 = _sample_record(tmp_path, status="completed")
        r2 = _sample_record(tmp_path, status="cancelled")
        with patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            save_run(r1)
            save_run(r2)
            history = load_history()
        assert len(history) == 2

    def test_prunes_to_100_records(self, tmp_path: Path) -> None:
        records = [_sample_record(tmp_path) for _ in range(105)]
        with patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            for r in records:
                save_run(r)
            history = load_history()
        assert len(history) == 100

    def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
        record = _sample_record(tmp_path)
        with patch("docu_studio.history.run_history.config_dir", return_value=tmp_path):
            save_run(record)
        assert (tmp_path / "run_history.json").exists()
