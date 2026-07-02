"""Run configuration screen — Guided / Full Auto mode, topic entry, duration."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from docu_studio.gui.tokens import (
    ACCENT, ACCENT_DARK, BG_CARD, BG_INPUT, BORDER,
    BTN_PRIMARY_BG, BTN_PRIMARY_HV, BTN_PRIMARY_TXT,
    BTN_SEC_BG, BTN_SEC_BORDER, BTN_SEC_HV, BTN_SEC_TXT,
    TEXT, SZ_3XL, font,
)
from docu_studio.config.settings import Settings

if TYPE_CHECKING:
    from docu_studio.gui.app import DocsStudioApp


class RunConfigScreen(ctk.CTkFrame):
    def __init__(self, app: "DocsStudioApp") -> None:
        super().__init__(app)
        self._app = app
        self._settings = Settings.load()
        self._mode_var = ctk.StringVar(value="guided")
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Configure Run",
                     font=font(SZ_3XL, "bold"), text_color=TEXT).pack(pady=(24, 12))

        # Mode toggle
        mode_frame = ctk.CTkFrame(self, fg_color="transparent")
        mode_frame.pack(pady=8)
        ctk.CTkRadioButton(
            mode_frame, text="Guided Mode", variable=self._mode_var, value="guided",
            command=self._on_mode_change,
        ).pack(side="left", padx=16)
        ctk.CTkRadioButton(
            mode_frame, text="Full Auto Mode", variable=self._mode_var, value="full_auto",
            command=self._on_mode_change,
        ).pack(side="left", padx=16)

        # Topic
        self._topic_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=8)
        self._topic_frame.pack(fill="x", padx=60, pady=6)
        ctk.CTkLabel(self._topic_frame, text="Topic:", anchor="w",
                     text_color=TEXT).pack(anchor="w", padx=12, pady=(10, 0))
        self._topic_entry = ctk.CTkEntry(
            self._topic_frame, placeholder_text="e.g. The Apollo 11 mission",
            fg_color=BG_INPUT, border_color=BORDER,
        )
        self._topic_entry.pack(fill="x", padx=12, pady=(4, 10))

        # Duration
        dur_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=8)
        dur_frame.pack(fill="x", padx=60, pady=6)
        self._dur_label = ctk.CTkLabel(dur_frame, text="Duration: 20 min",
                                       anchor="w", text_color=TEXT)
        self._dur_label.pack(anchor="w", padx=12, pady=(10, 0))
        self._dur_slider = ctk.CTkSlider(
            dur_frame, from_=5, to=120, number_of_steps=115,
            progress_color=ACCENT, fg_color=BG_INPUT,
            button_color=ACCENT, button_hover_color=ACCENT_DARK,
            command=self._on_dur,
        )
        self._dur_slider.set(20)
        self._dur_slider.pack(fill="x", padx=12, pady=(4, 10))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=24)
        ctk.CTkButton(
            btn_frame, text="Cancel", width=110,
            fg_color=BTN_SEC_BG, hover_color=BTN_SEC_HV, text_color=BTN_SEC_TXT,
            border_width=1, border_color=BTN_SEC_BORDER,
            command=self._cancel,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            btn_frame, text="Start Run", width=130,
            fg_color=BTN_PRIMARY_BG, hover_color=BTN_PRIMARY_HV, text_color=BTN_PRIMARY_TXT,
            command=self.start_run,
        ).pack(side="left", padx=8)

    def _on_mode_change(self) -> None:
        if self._mode_var.get() == "full_auto":
            self._topic_frame.pack_forget()
        else:
            self._topic_frame.pack(fill="x", padx=60, pady=6)

    def _on_dur(self, value: float) -> None:
        self._dur_label.configure(text=f"Duration: {int(value)} min")

    def _cancel(self) -> None:
        from docu_studio.gui.screens.main_screen import MainScreen
        self._app.show_screen(MainScreen(self._app))

    def start_run(self) -> None:
        from docu_studio.adapters.llm.anthropic_adapter import AnthropicAdapter
        from docu_studio.adapters.tts.edge_tts_adapter import EdgeTTSAdapter
        from docu_studio.adapters.tts.elevenlabs_adapter import ElevenLabsAdapter
        from docu_studio.adapters.footage.pexels_adapter import PexelsAdapter
        from docu_studio.adapters.footage.pixabay_adapter import PixabayAdapter
        from docu_studio.pipeline.runner import PipelineRunner, RunMode
        from docu_studio.gui.screens.progress_screen import ProgressScreen

        mode_str = self._mode_var.get()
        topic = self._topic_entry.get().strip() if mode_str == "guided" else ""
        duration = int(self._dur_slider.get())

        settings = self._settings
        llm = AnthropicAdapter(settings)
        tts: object
        if settings.tts_provider == "elevenlabs":
            tts = ElevenLabsAdapter(settings)
        else:
            tts = EdgeTTSAdapter()

        footage_providers = []
        if "pexels" in settings.footage_providers:
            footage_providers.append(PexelsAdapter(settings))
        if "pixabay" in settings.footage_providers:
            footage_providers.append(PixabayAdapter(settings))

        output_base = Path(settings.output_folder) if settings.output_folder else Path.home() / "DocuStudio"
        output_base.mkdir(parents=True, exist_ok=True)

        runner = PipelineRunner(
            topic=topic,
            duration_minutes=duration,
            mode=RunMode(mode_str),
            llm=llm,
            tts=tts,  # type: ignore[arg-type]
            footage_providers=footage_providers,
            output_base=output_base,
        )

        progress_screen = ProgressScreen(self._app, runner)
        self._app.attach_event_queue(runner.event_queue)
        self._app.show_screen(progress_screen)
        runner.start()
