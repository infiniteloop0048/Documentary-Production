"""Shared pytest fixtures for docu_studio tests."""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Return a temporary directory simulating a project output folder."""
    d = tmp_path / "test_project"
    d.mkdir()
    return d
