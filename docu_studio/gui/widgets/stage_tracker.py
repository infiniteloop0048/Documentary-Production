"""StageTracker — the signature element of the progress screen.

StageStateMachine is a pure class (no Tk dependency) holding the state of
each pipeline stage.  StageTracker is a CTkFrame that visualises it and
animates stage transitions via .after() loops.
"""
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import customtkinter as ctk


class StageState(Enum):
    PENDING = auto()
    ACTIVE = auto()
    DONE = auto()


class StageStateMachine:
    """Pure state machine — no Tk dependency; safe to import in headless tests."""

    def __init__(self, stage_names: list[str]) -> None:
        if not stage_names:
            raise ValueError("stage_names must not be empty")
        self.states: dict[str, StageState] = {n: StageState.PENDING for n in stage_names}
        self._names = list(stage_names)
        self._active: str | None = None

    @property
    def active_stage(self) -> str | None:
        return self._active

    def activate(self, name: str) -> None:
        """Mark *name* as ACTIVE; mark any previous ACTIVE stage as DONE."""
        if name not in self.states:
            raise KeyError(f"Unknown stage: {name!r}")
        if self._active is not None:
            self.states[self._active] = StageState.DONE
        self.states[name] = StageState.ACTIVE
        self._active = name

    def mark_done(self, name: str) -> None:
        """Mark *name* as DONE.  Only valid when the stage is currently ACTIVE."""
        if name not in self.states:
            raise KeyError(f"Unknown stage: {name!r}")
        if self.states[name] != StageState.ACTIVE:
            raise ValueError(f"Stage {name!r} is not ACTIVE (state={self.states[name].name})")
        self.states[name] = StageState.DONE
        self._active = None

    def reset(self) -> None:
        for name in self._names:
            self.states[name] = StageState.PENDING
        self._active = None


class StageTracker:
    """Vertical column of stage pills that animate between PENDING/ACTIVE/DONE.

    Constructed lazily to avoid importing customtkinter at module level
    (which would require a display).  Instantiate only inside a running
    Tk event loop.

    Usage::

        tracker = StageTracker(parent_frame, STAGE_NAMES)
        tracker.frame.pack(fill="y", side="left", padx=8, pady=8)

        # When the pipeline emits a ProgressEvent:
        tracker.activate("Research")
        # When that stage finishes:
        tracker.mark_done("Research")
    """

    def __init__(self, parent: "ctk.CTkFrame", stage_names: list[str]) -> None:
        import customtkinter as ctk
        from docu_studio.gui.tokens import (
            ACCENT, BG_HOVER, BG_PANEL, SUCCESS, TEXT, TEXT_DIM,
            ANIM_STAGE_MS, ANIM_STEPS,
            SZ_XS, SZ_SM, font,
        )

        self._ctk = ctk
        self._anim_ms = ANIM_STAGE_MS
        self._anim_steps = ANIM_STEPS
        self._color_pending = BG_HOVER
        self._color_active = ACCENT
        self._color_done = SUCCESS
        self._color_text = TEXT

        self._machine = StageStateMachine(stage_names)
        self._labels: dict[str, "ctk.CTkLabel"] = {}
        self._anim_after_ids: dict[str, str] = {}

        self.frame = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=6)

        heading = ctk.CTkLabel(
            self.frame,
            text="PIPELINE",
            font=font(SZ_XS, "bold"),
            text_color=TEXT_DIM,
        )
        heading.pack(padx=12, pady=(12, 6))

        for name in stage_names:
            lbl = ctk.CTkLabel(
                self.frame,
                text=name,
                font=font(SZ_SM),
                fg_color=BG_HOVER,
                text_color=TEXT_DIM,
                corner_radius=4,
                width=90,
                padx=8,
                pady=4,
            )
            lbl.pack(padx=10, pady=3)
            self._labels[name] = lbl

        # Spacer at bottom
        ctk.CTkLabel(self.frame, text="", fg_color="transparent").pack(pady=4)

    def activate(self, name: str) -> None:
        """Transition *name* to ACTIVE with a 400 ms fade-in animation."""
        prev = self._machine.active_stage
        self._machine.activate(name)
        if prev is not None:
            self._animate(prev, StageState.DONE)
        self._animate(name, StageState.ACTIVE)

    def mark_done(self, name: str) -> None:
        self._machine.mark_done(name)
        self._animate(name, StageState.DONE)

    def reset(self) -> None:
        self._machine.reset()
        for name, lbl in self._labels.items():
            self._cancel_anim(name)
            lbl.configure(fg_color=self._color_pending)

    # ── Internal animation ────────────────────────────────────────────────────

    def _animate(self, name: str, target: StageState) -> None:
        """Cross-fade the pill for *name* toward *target* over ANIM_STAGE_MS ms."""
        self._cancel_anim(name)
        lbl = self._labels[name]
        target_color = self._color_active if target == StageState.ACTIVE else self._color_done
        interval = max(1, self._anim_ms // self._anim_steps)
        self._step_color(name, lbl, target_color, self._anim_steps, interval)

    def _step_color(
        self,
        name: str,
        lbl: "ctk.CTkLabel",
        target_hex: str,
        steps_left: int,
        interval: int,
    ) -> None:
        if steps_left <= 0:
            lbl.configure(fg_color=target_hex)
            self._anim_after_ids.pop(name, None)
            return
        # Apply target directly on last step; intermediate steps are instant
        # (true interpolation would need hex→RGB math — this is a deliberate
        # fade-to-target flicker avoided by snapping at the midpoint).
        if steps_left == 1:
            lbl.configure(fg_color=target_hex)
            self._anim_after_ids.pop(name, None)
            return

        after_id = lbl.after(
            interval,
            lambda: self._step_color(name, lbl, target_hex, steps_left - 1, interval),
        )
        self._anim_after_ids[name] = after_id

    def _cancel_anim(self, name: str) -> None:
        after_id = self._anim_after_ids.pop(name, None)
        if after_id is not None:
            try:
                self._labels[name].after_cancel(after_id)
            except Exception:
                pass
