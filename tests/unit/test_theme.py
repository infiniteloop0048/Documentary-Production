"""Tests for docu_studio.gui.theme — pure builder, no Tk display required."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def theme_module():
    from docu_studio.gui import theme as t
    return t


def test_theme_json_exists():
    here = Path(__file__).parents[2] / "docu_studio" / "gui" / "pitch_dark.json"
    assert here.exists(), "pitch_dark.json must exist next to theme.py"


def test_theme_json_is_valid_json():
    path = Path(__file__).parents[2] / "docu_studio" / "gui" / "pitch_dark.json"
    data = json.loads(path.read_text())
    assert isinstance(data, dict)


def test_theme_json_contains_required_widget_keys():
    path = Path(__file__).parents[2] / "docu_studio" / "gui" / "pitch_dark.json"
    data = json.loads(path.read_text())
    required = {"CTk", "CTkButton", "CTkLabel", "CTkEntry", "CTkFrame"}
    missing = required - data.keys()
    assert not missing, f"Theme JSON missing keys: {missing}"


def test_theme_json_button_uses_halide():
    from docu_studio.gui.tokens import COLOR_HALIDE
    path = Path(__file__).parents[2] / "docu_studio" / "gui" / "pitch_dark.json"
    data = json.loads(path.read_text())
    dark_value = data["CTkButton"]["fg_color"][1]
    assert dark_value == COLOR_HALIDE, f"Button dark fg should be Halide {COLOR_HALIDE}, got {dark_value}"


def test_theme_json_label_text_color_dark_is_bond():
    from docu_studio.gui.tokens import COLOR_BOND
    path = Path(__file__).parents[2] / "docu_studio" / "gui" / "pitch_dark.json"
    data = json.loads(path.read_text())
    dark_value = data["CTkLabel"]["text_color"][1]
    assert dark_value == COLOR_BOND, f"Label dark text_color should be Bond {COLOR_BOND}, got {dark_value}"


def test_theme_json_root_bg_dark_is_pitch():
    from docu_studio.gui.tokens import COLOR_PITCH
    path = Path(__file__).parents[2] / "docu_studio" / "gui" / "pitch_dark.json"
    data = json.loads(path.read_text())
    dark_value = data["CTk"]["fg_color"][1]
    assert dark_value == COLOR_PITCH, f"Root dark bg should be Pitch {COLOR_PITCH}, got {dark_value}"


def test_theme_file_path_constant_points_to_existing_file(theme_module):
    assert theme_module.THEME_FILE.exists()


def test_theme_file_path_is_absolute(theme_module):
    assert theme_module.THEME_FILE.is_absolute()
