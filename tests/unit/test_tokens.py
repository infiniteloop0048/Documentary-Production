"""Tests for docu_studio.gui.tokens — pure constants, no Tk required."""
from __future__ import annotations

import re

import pytest

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@pytest.fixture(scope="module")
def tokens():
    from docu_studio.gui import tokens as t
    return t


def test_all_color_constants_are_valid_hex(tokens):
    colors = [
        tokens.COLOR_PITCH,
        tokens.COLOR_BOND,
        tokens.COLOR_HALIDE,
        tokens.COLOR_GRADE,
        tokens.COLOR_CUE,
        tokens.COLOR_HALIDE_HOVER,
        tokens.COLOR_PITCH_SURFACE,
        tokens.COLOR_PITCH_MID,
    ]
    for c in colors:
        assert HEX_RE.match(c), f"{c!r} is not a valid 6-digit hex color"


def test_font_display_chain_is_nonempty_strings(tokens):
    assert len(tokens.FONT_DISPLAY) >= 2
    assert all(isinstance(f, str) and f for f in tokens.FONT_DISPLAY)


def test_font_body_chain_is_nonempty_strings(tokens):
    assert len(tokens.FONT_BODY) >= 2
    assert all(isinstance(f, str) and f for f in tokens.FONT_BODY)


def test_stage_names_has_five_entries(tokens):
    assert len(tokens.STAGE_NAMES) == 5
    assert all(isinstance(s, str) and s for s in tokens.STAGE_NAMES)


def test_anim_stage_ms_is_positive(tokens):
    assert tokens.ANIM_STAGE_MS > 0
    assert tokens.ANIM_STEPS > 0


def test_resolve_font_returns_first_when_all_available(tokens):
    available = frozenset(tokens.FONT_DISPLAY)
    result = tokens.resolve_font(tokens.FONT_DISPLAY, available)
    assert result == tokens.FONT_DISPLAY[0]


def test_resolve_font_skips_unavailable(tokens):
    available = frozenset([tokens.FONT_DISPLAY[-1]])
    result = tokens.resolve_font(tokens.FONT_DISPLAY, available)
    assert result == tokens.FONT_DISPLAY[-1]


def test_resolve_font_falls_back_to_last_when_none_available(tokens):
    result = tokens.resolve_font(tokens.FONT_DISPLAY, frozenset())
    assert result == tokens.FONT_DISPLAY[-1]


def test_resolve_font_no_available_arg_returns_first(tokens):
    result = tokens.resolve_font(tokens.FONT_DISPLAY)
    assert result == tokens.FONT_DISPLAY[0]


def test_get_display_family_returns_nonempty_string(tokens):
    result = tokens.get_display_family()
    assert isinstance(result, str) and result


def test_radius_and_border_are_nonnegative(tokens):
    assert tokens.RADIUS >= 0
    assert tokens.BORDER_WIDTH >= 0
