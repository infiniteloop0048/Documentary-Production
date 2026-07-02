"""Progress screen — stage tracker, scene counter, scrollable log, Cancel button."""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from docu_studio.gui.tokens import (
    BG_INPUT, ERROR, INFO, TEXT, TEXT_DIM, WARNING, SZ_SM, SZ_3XL, font, STAGE_NAMES,
)
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent

if TYPE_CHECKING:
    from docu_studio.gui.app import DocsStudioApp
    from docu_studio.pipeline.runner import PipelineRunner


_LEVEL_COLOR = {
    LogLevel.INFO: None,
    LogLevel.WARNING: WARNING,
    LogLevel.ERROR: ERROR,
}


class ProgressScreen(ctk.CTkFrame):
    def __init__(self, app: "DocsStudioApp", runner: "PipelineRunner") -> None:
        super().__init__(app)
        self._app = app
        self._runner = runner
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Running Pipeline",
                     font=font(SZ_3XL, "bold"), text_color=TEXT).pack(pady=(20, 8))

        # Body: stage tracker (left) + log area (right)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        from docu_studio.gui.widgets.stage_tracker import StageTracker
        self._tracker = StageTracker(body, STAGE_NAMES)
        self._tracker.frame.pack(side="left", fill="y", padx=(0, 12), pady=0)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self._scene_label = ctk.CTkLabel(
            right, text="", anchor="w", font=font(SZ_SM), text_color=TEXT_DIM
        )
        self._scene_label.pack(anchor="w", pady=(0, 4))

        self._log = ctk.CTkScrollableFrame(right, label_text="Log", fg_color=BG_INPUT)
        self._log.pack(fill="both", expand=True)

        # Cancel button
        self._cancel_btn = ctk.CTkButton(
            self, text="Cancel", fg_color=ERROR, command=self._cancel
        )
        self._cancel_btn.pack(pady=(8, 20))

    def handle_event(self, event: object) -> None:
        if event is None:
            self._on_run_finished()
            return

        if isinstance(event, ProgressEvent):
            try:
                self._tracker.activate(event.stage)
            except (KeyError, ValueError):
                pass
            if event.scene_index is not None and event.scene_total is not None:
                self._scene_label.configure(
                    text=f"Scene {event.scene_index} of {event.scene_total}"
                )
            else:
                self._scene_label.configure(text="")
            self._append_log(event.message, color=None)

        elif isinstance(event, LogEvent):
            self._append_log(event.message, color=_LEVEL_COLOR.get(event.level))

        elif isinstance(event, ErrorEvent):
            color = ERROR if event.fatal else WARNING
            prefix = "[FATAL] " if event.fatal else "[WARNING] "
            self._append_log(prefix + event.message, color=color)

    def _append_log(self, text: str, color: str | None) -> None:
        kwargs: dict = {
            "text": text, "anchor": "w", "justify": "left",
            "wraplength": 800, "font": font(SZ_SM, mono=True),
        }
        if color is not None:
            kwargs["text_color"] = color
        lbl = ctk.CTkLabel(self._log, **kwargs)
        lbl.pack(anchor="w", padx=4, pady=1)

    def _cancel(self) -> None:
        self._runner.cancel_event.set()
        self._cancel_btn.configure(state="disabled", text="Cancelling…")

    def _on_run_finished(self) -> None:
        self._app.detach_event_queue()
        self._cancel_btn.configure(state="disabled")
        from docu_studio.gui.screens.main_screen import MainScreen
        self._app.show_screen(MainScreen(self._app))
