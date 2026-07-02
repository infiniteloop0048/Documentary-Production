"""Tests for StageState logic — no Tk display required."""
from __future__ import annotations

import pytest

from docu_studio.gui.widgets.stage_tracker import StageState, StageStateMachine


def _machine(names=None):
    return StageStateMachine(names or ["Research", "Script", "Voice", "Footage", "Render"])


def test_initial_all_stages_pending():
    m = _machine()
    assert all(s == StageState.PENDING for s in m.states.values())


def test_activate_first_stage():
    m = _machine()
    m.activate("Research")
    assert m.states["Research"] == StageState.ACTIVE
    assert m.states["Script"] == StageState.PENDING


def test_activate_marks_previous_done():
    m = _machine()
    m.activate("Research")
    m.activate("Script")
    assert m.states["Research"] == StageState.DONE
    assert m.states["Script"] == StageState.ACTIVE
    assert m.states["Voice"] == StageState.PENDING


def test_activate_unknown_stage_raises():
    m = _machine()
    with pytest.raises(KeyError):
        m.activate("NonExistent")


def test_complete_all_stages():
    m = _machine()
    names = ["Research", "Script", "Voice", "Footage", "Render"]
    for name in names:
        m.activate(name)
    m.mark_done("Render")
    assert all(s == StageState.DONE for s in m.states.values())


def test_reset_returns_all_to_pending():
    m = _machine()
    m.activate("Research")
    m.activate("Script")
    m.reset()
    assert all(s == StageState.PENDING for s in m.states.values())


def test_stage_names_are_preserved_in_order():
    names = ["A", "B", "C"]
    m = StageStateMachine(names)
    assert list(m.states.keys()) == names


def test_mark_done_on_pending_stage_raises():
    m = _machine()
    with pytest.raises(ValueError):
        m.mark_done("Research")


def test_active_stage_property_none_when_idle():
    m = _machine()
    assert m.active_stage is None


def test_active_stage_property_returns_current():
    m = _machine()
    m.activate("Voice")
    assert m.active_stage == "Voice"
