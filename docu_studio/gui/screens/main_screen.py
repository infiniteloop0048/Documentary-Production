"""Main screen — scrollable run history and Start New Run button."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from docu_studio.gui.tokens import (
    BG_CARD, BTN_PRIMARY_BG, BTN_PRIMARY_HV, BTN_PRIMARY_TXT,
    BTN_SEC_BG, BTN_SEC_BORDER, BTN_SEC_HV, BTN_SEC_TXT,
    ERROR, SUCCESS, TEXT, TEXT_DIM, WARNING, SZ_SM, SZ_3XL, font,
)
from docu_studio.history.run_history import RunRecord, load_history
from docu_studio import platform_layer  # Open Folder uses platform_layer only (Constitution VI)

if TYPE_CHECKING:
    from docu_studio.gui.app import DocsStudioApp


class MainScreen(ctk.CTkFrame):
    def __init__(self, app: "DocsStudioApp") -> None:
        super().__init__(app)
        self._app = app
        self._build()

    def _build(self) -> None:
        # Header row
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 0))
        ctk.CTkLabel(header, text="Documentary Studio",
                     font=font(SZ_3XL, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkButton(
            header, text="Settings", width=100,
            fg_color=BTN_SEC_BG, hover_color=BTN_SEC_HV, text_color=BTN_SEC_TXT,
            border_width=1, border_color=BTN_SEC_BORDER,
            command=self._open_settings,
        ).pack(side="right")
        ctk.CTkButton(
            header, text="Start New Run", width=140,
            fg_color=BTN_PRIMARY_BG, hover_color=BTN_PRIMARY_HV, text_color=BTN_PRIMARY_TXT,
            command=self._start_run,
        ).pack(side="right", padx=(0, 8))

        # History scroll area
        self._scroll = ctk.CTkScrollableFrame(self, label_text="Recent Runs")
        self._scroll.pack(fill="both", expand=True, padx=16, pady=12)
        self._load_history()

    def _load_history(self) -> None:
        for widget in self._scroll.winfo_children():
            widget.destroy()
        records = list(reversed(load_history()))
        if not records:
            ctk.CTkLabel(self._scroll, text="No runs yet.",
                         text_color=TEXT_DIM, font=font(SZ_SM)).pack(pady=20)
            return
        for run in records:
            self._add_row(run)

    def _add_row(self, run: RunRecord) -> None:
        row = ctk.CTkFrame(self._scroll, fg_color=BG_CARD, corner_radius=6)
        row.pack(fill="x", pady=3)
        date_str = run.started_at.strftime("%Y-%m-%d %H:%M")
        status_color = {"completed": SUCCESS, "cancelled": WARNING, "failed": ERROR}.get(
            run.status, TEXT_DIM
        )
        ctk.CTkLabel(row, text=run.topic, anchor="w", width=350).pack(side="left", padx=8)
        ctk.CTkLabel(row, text=date_str, anchor="w", width=140).pack(side="left")
        ctk.CTkLabel(
            row, text=run.status.upper(), text_color=status_color, width=100
        ).pack(side="left")
        ctk.CTkButton(
            row, text="Open Folder", width=110,
            fg_color=BTN_SEC_BG, hover_color=BTN_SEC_HV, text_color=BTN_SEC_TXT,
            border_width=1, border_color=BTN_SEC_BORDER,
            command=lambda p=run.project_folder: platform_layer.open_folder(p),
        ).pack(side="right", padx=8)

    def _start_run(self) -> None:
        from docu_studio.gui.screens.run_config_screen import RunConfigScreen
        self._app.show_screen(RunConfigScreen(self._app))

    def _open_settings(self) -> None:
        from docu_studio.gui.screens.settings_screen import SettingsScreen
        self._app.show_screen(SettingsScreen(self._app))
