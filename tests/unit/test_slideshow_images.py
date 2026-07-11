"""Unit tests for validate_manual_images — filesystem-backed, uses tmp_path."""
from __future__ import annotations

from pathlib import Path

import pytest

from docu_studio.slideshow.slideshow_images import (
    InvalidImageListError,
    validate_manual_images,
)


class TestValidateManualImages:
    def test_empty_list_raises(self) -> None:
        with pytest.raises(InvalidImageListError, match="At least one image"):
            validate_manual_images([])

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidImageListError, match="not found"):
            validate_manual_images([str(tmp_path / "missing.jpg")])

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "notes.txt"
        bad.write_text("hi")
        with pytest.raises(InvalidImageListError, match="Unsupported image format"):
            validate_manual_images([str(bad)])

    def test_valid_list_preserves_order(self, tmp_path: Path) -> None:
        first = tmp_path / "b.png"
        second = tmp_path / "a.jpg"
        first.write_bytes(b"\x89PNG")
        second.write_bytes(b"\xff\xd8\xff")
        result = validate_manual_images([str(first), str(second)])
        assert result == [str(first), str(second)]

    def test_case_insensitive_extension(self, tmp_path: Path) -> None:
        upper = tmp_path / "photo.JPG"
        upper.write_bytes(b"\xff\xd8\xff")
        assert validate_manual_images([str(upper)]) == [str(upper)]
