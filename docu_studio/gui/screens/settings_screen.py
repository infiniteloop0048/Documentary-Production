"""Settings screen — LLM provider, TTS, footage, topic discovery, output."""
from __future__ import annotations

import threading
import tkinter.filedialog as filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from docu_studio.config import key_cache
from docu_studio.config.settings import Settings
from docu_studio.gui.tokens import (
    ACCENT, ACCENT_DARK, BG_CARD, BG_HOVER, BG_INPUT, BG_PANEL,
    BORDER, BORDER_STRONG, BTN_PRIMARY_BG, BTN_PRIMARY_HV, BTN_PRIMARY_TXT,
    BTN_SEC_BG, BTN_SEC_BORDER, BTN_SEC_HV, BTN_SEC_TXT,
    FONT_MONO, FONT_UI,
    SECTION_FOOTAGE, SECTION_TOPIC, SECTION_TTS,
    SUCCESS, TEXT, TEXT_DIM, TEXT_FAINT,
    SZ_MD, SZ_SM, SZ_XL,
)
from docu_studio.gui.widgets.section_card import SectionCard

if TYPE_CHECKING:
    from docu_studio.gui.app import DocsStudioApp

_LLM_PROVIDERS = ["Anthropic", "OpenAI", "OpenRouter", "Groq"]

_MODEL_MAP: dict[str, list[str]] = {
    "Anthropic":  ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"],
    "OpenAI":     ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini", "o3-mini"],
    "OpenRouter": [
        "openai/gpt-4o",
        "anthropic/claude-sonnet-4-5",
        "meta-llama/llama-3.1-70b-instruct",
        "google/gemini-pro-1.5",
        "mistralai/mistral-large",
    ],
    "Groq": ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"],
}

_DEEPGRAM_VOICES = [
    "aura-asteria-en", "aura-luna-en", "aura-stella-en", "aura-athena-en", "aura-hera-en",
]

_PROVIDER_KEYRING: dict[str, str] = {
    "Anthropic":  "anthropic",
    "OpenAI":     "docu_studio_openai_key",
    "OpenRouter": "docu_studio_openrouter_key",
    "Groq":       "docu_studio_groq_key",
}


def _fix_all_cursors(widget: object) -> None:
    try:
        widget.configure(cursor="arrow")  # type: ignore[union-attr]
    except Exception:
        pass
    try:
        for child in widget.winfo_children():  # type: ignore[union-attr]
            _fix_all_cursors(child)
    except Exception:
        pass


def _row(parent: ctk.CTkFrame, label_text: str) -> ctk.CTkFrame:
    """152 px label left; right frame left-aligned (no expand)."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=5)
    ctk.CTkLabel(
        row, text=label_text, width=152, anchor="w",
        font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
        text_color=TEXT_DIM,
    ).pack(side="left")
    right = ctk.CTkFrame(row, fg_color="transparent")
    right.pack(side="left")
    return right


def _secret_entry(parent: ctk.CTkFrame, placeholder: str = "",
                  width: int = 280) -> ctk.CTkEntry:
    """Password entry + Reveal/Hide toggle. Returns entry only."""
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.pack(side="left")
    entry = ctk.CTkEntry(
        wrap,
        show="•", placeholder_text=placeholder,
        width=width, height=34,
        fg_color=BG_INPUT, border_color=BORDER,
        text_color=TEXT, placeholder_text_color=TEXT_FAINT,
        font=ctk.CTkFont(family=FONT_MONO, size=SZ_SM),
        corner_radius=4,
    )
    entry.pack(side="left")

    def _toggle() -> None:
        if entry.cget("show") == "•":
            entry.configure(show="")
            btn.configure(text="Hide")
        else:
            entry.configure(show="•")
            btn.configure(text="Reveal")

    btn = ctk.CTkButton(
        wrap, text="Reveal", width=72, height=34,
        fg_color=BG_CARD, hover_color=BG_HOVER,
        text_color=TEXT_DIM, border_color=BORDER, border_width=1,
        font=ctk.CTkFont(family=FONT_UI, size=SZ_SM),
        corner_radius=4, cursor="arrow",
        command=_toggle,
    )
    btn.pack(side="left", padx=(6, 0))
    return entry


class SettingsScreen(ctk.CTkFrame):
    def __init__(self, app: "DocsStudioApp") -> None:
        super().__init__(app)
        self._app = app
        self._settings = Settings.load()
        self._tts_var: str = (
            self._settings.tts_provider
            if self._settings.tts_provider in ("elevenlabs", "deepgram")
            else "elevenlabs"
        )
        self._footage_enabled: dict[str, bool] = {
            p: p in self._settings.footage_providers for p in ("pexels", "pixabay")
        }
        self._build()

    def _build(self) -> None:
        self._build_footer()

        nav = ctk.CTkFrame(self, fg_color=BG_PANEL, height=48, corner_radius=0)
        nav.pack(fill="x", side="top")
        nav.pack_propagate(False)
        ctk.CTkButton(
            nav, text="← Back",
            width=88, height=32,
            fg_color=BG_CARD, hover_color=BG_HOVER,
            text_color=TEXT, border_color=BORDER, border_width=1,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            corner_radius=4, cursor="arrow",
            command=self._cancel,
        ).pack(side="left", padx=14, pady=8)
        ctk.CTkLabel(
            nav, text="Settings",
            font=ctk.CTkFont(family=FONT_UI, size=SZ_XL, weight="bold"),
            text_color=TEXT,
        ).pack(side="left", padx=6)

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_PANEL)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        self._build_llm_section(scroll)
        self._build_tts_section(scroll)
        self._build_footage_section(scroll)
        self._build_topic_section(scroll)
        self._build_output_section(scroll)
        self.after(80, lambda: _fix_all_cursors(self))

    def _build_llm_section(self, parent: ctk.CTkScrollableFrame) -> None:
        card = SectionCard(parent, "LLM Provider", icon="🤖", accent=ACCENT)
        card.pack(fill="x", pady=(0, 12))

        r = _row(card.body, "Provider")
        self._llm_provider_menu = ctk.CTkOptionMenu(
            r, values=_LLM_PROVIDERS,
            command=self._on_provider_change,
            width=200, height=34,
            fg_color=BG_INPUT, button_color=BG_HOVER,
            button_hover_color=BORDER_STRONG,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_HOVER,
            dropdown_text_color=TEXT, text_color=TEXT,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            dropdown_font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            corner_radius=4, anchor="w", cursor="arrow",
        )
        self._llm_provider_menu.set(self._settings.llm_provider)
        self._llm_provider_menu.pack(side="left")

        r2 = _row(card.body, "Model")
        initial_models = _MODEL_MAP.get(self._settings.llm_provider, _MODEL_MAP["Anthropic"])
        self._llm_model_menu = ctk.CTkOptionMenu(
            r2, values=initial_models,
            width=280, height=34,
            fg_color=BG_INPUT, button_color=BG_HOVER,
            button_hover_color=BORDER_STRONG,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_HOVER,
            dropdown_text_color=TEXT, text_color=TEXT,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            dropdown_font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            corner_radius=4, anchor="w", cursor="arrow",
        )
        self._llm_model_menu.set(
            self._settings.llm_model
            if self._settings.llm_model in initial_models
            else initial_models[0]
        )
        self._llm_model_menu.pack(side="left")

        r3 = _row(card.body, "API Key")
        self._llm_key_entry = _secret_entry(r3, "Paste your API key", width=340)
        existing = key_cache.get(_PROVIDER_KEYRING[self._settings.llm_provider])
        if existing:
            self._llm_key_entry.insert(0, existing)

    def _on_provider_change(self, provider: str) -> None:
        models = _MODEL_MAP.get(provider, [])
        self._llm_model_menu.configure(values=models)
        self._llm_model_menu.set(models[0] if models else "")
        self._llm_key_entry.delete(0, "end")
        existing = key_cache.get(_PROVIDER_KEYRING.get(provider, ""))
        if existing:
            self._llm_key_entry.insert(0, existing)

    def _build_tts_section(self, parent: ctk.CTkScrollableFrame) -> None:
        card = SectionCard(parent, "Text-to-Speech", icon="🎙️", accent=SECTION_TTS)
        card.pack(fill="x", pady=(0, 12))

        def _sel_tts(p: str) -> None:
            self._tts_var = p
            self._el_btn.configure(
                fg_color=ACCENT if p == "elevenlabs" else BG_INPUT,
                hover_color=ACCENT_DARK if p == "elevenlabs" else BG_HOVER,
                text_color=BTN_PRIMARY_TXT if p == "elevenlabs" else TEXT_DIM,
                border_color=ACCENT if p == "elevenlabs" else BORDER,
            )
            self._dg_btn.configure(
                fg_color=ACCENT if p == "deepgram" else BG_INPUT,
                hover_color=ACCENT_DARK if p == "deepgram" else BG_HOVER,
                text_color=BTN_PRIMARY_TXT if p == "deepgram" else TEXT_DIM,
                border_color=ACCENT if p == "deepgram" else BORDER,
            )

        tts_r = _row(card.body, "Provider")
        tf = ctk.CTkFrame(tts_r, fg_color="transparent")
        tf.pack(side="left")

        _kw: dict = dict(
            width=120, height=34, corner_radius=4, border_width=1,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD, weight="bold"),
            cursor="arrow",
        )

        el_active = self._tts_var == "elevenlabs"
        _el = ctk.CTkButton(
            tf, text="ElevenLabs",
            fg_color=ACCENT if el_active else BG_INPUT,
            hover_color=ACCENT_DARK if el_active else BG_HOVER,
            text_color=BTN_PRIMARY_TXT if el_active else TEXT_DIM,
            border_color=ACCENT if el_active else BORDER,
            command=lambda: _sel_tts("elevenlabs"),
            **_kw,
        )
        _el.pack(side="left", padx=(0, 8))
        self._el_btn = _el

        dg_active = self._tts_var == "deepgram"
        _dg = ctk.CTkButton(
            tf, text="Deepgram",
            fg_color=ACCENT if dg_active else BG_INPUT,
            hover_color=ACCENT_DARK if dg_active else BG_HOVER,
            text_color=BTN_PRIMARY_TXT if dg_active else TEXT_DIM,
            border_color=ACCENT if dg_active else BORDER,
            command=lambda: _sel_tts("deepgram"),
            **_kw,
        )
        _dg.pack(side="left")
        self._dg_btn = _dg

        r = _row(card.body, "ElevenLabs Key")
        self._el_key = _secret_entry(r, "sk_…", width=320)
        el = key_cache.get("elevenlabs")
        if el:
            self._el_key.insert(0, el)

        r2 = _row(card.body, "Deepgram Key")
        self._dg_key = _secret_entry(r2, "Token …", width=320)
        dg = key_cache.get("docu_studio_deepgram_key")
        if dg:
            self._dg_key.insert(0, dg)

        r3 = _row(card.body, "Deepgram Voice")
        self._dg_voice = ctk.CTkOptionMenu(
            r3, values=_DEEPGRAM_VOICES,
            width=220, height=34,
            fg_color=BG_INPUT, button_color=BG_HOVER,
            button_hover_color=BORDER_STRONG,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_HOVER,
            dropdown_text_color=TEXT, text_color=TEXT,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            dropdown_font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            corner_radius=4, anchor="w", cursor="arrow",
        )
        self._dg_voice.set(self._settings.deepgram_voice)
        self._dg_voice.pack(side="left")

    def _build_footage_section(self, parent: ctk.CTkScrollableFrame) -> None:
        card = SectionCard(parent, "Stock Footage", icon="🎬", accent=SECTION_FOOTAGE)
        card.pack(fill="x", pady=(0, 12))

        for label, svc in [("Pexels", "pexels"), ("Pixabay", "pixabay")]:
            enabled = self._footage_enabled[svc]

            def _make_toggle(p: str, lbl: str):  # noqa: ANN202
                def _tog() -> None:
                    self._footage_enabled[p] = not self._footage_enabled[p]
                    on = self._footage_enabled[p]
                    getattr(self, f"_{p}_toggle_btn").configure(
                        text=f"✓  {lbl}" if on else f"   {lbl}",
                        fg_color=ACCENT if on else BG_INPUT,
                        hover_color=ACCENT_DARK if on else BG_HOVER,
                        text_color=BTN_PRIMARY_TXT if on else TEXT_DIM,
                        border_color=ACCENT if on else BORDER,
                    )
                return _tog

            row_r = _row(card.body, "")
            tog = ctk.CTkButton(
                row_r,
                text=f"✓  {label}" if enabled else f"   {label}",
                width=110, height=34, corner_radius=4, border_width=1,
                fg_color=ACCENT if enabled else BG_INPUT,
                hover_color=ACCENT_DARK if enabled else BG_HOVER,
                text_color=BTN_PRIMARY_TXT if enabled else TEXT_DIM,
                border_color=ACCENT if enabled else BORDER,
                font=ctk.CTkFont(family=FONT_UI, size=SZ_MD, weight="bold"),
                cursor="arrow",
                command=_make_toggle(svc, label),
            )
            tog.pack(side="left", padx=(0, 10))
            setattr(self, f"_{svc}_toggle_btn", tog)

            key_entry = _secret_entry(row_r, f"{label} API Key", width=300)
            existing = key_cache.get(svc)
            if existing:
                key_entry.insert(0, existing)
            setattr(self, f"_{svc}_key_entry", key_entry)

    def _build_topic_section(self, parent: ctk.CTkScrollableFrame) -> None:
        card = SectionCard(parent, "Topic Discovery", icon="🔍", accent=SECTION_TOPIC)
        card.pack(fill="x", pady=(0, 12))

        r = _row(card.body, "Serper.dev Key")
        self._serper_key_entry = _secret_entry(r, placeholder="serper.dev api key")
        existing = key_cache.get("serper")
        if existing:
            self._serper_key_entry.insert(0, existing)

    def _build_output_section(self, parent: ctk.CTkScrollableFrame) -> None:
        card = SectionCard(parent, "Output & Narration", icon="📁", accent=BORDER_STRONG)
        card.pack(fill="x", pady=(0, 12))

        r = _row(card.body, "Output Folder")
        self._folder_entry = ctk.CTkEntry(
            r, fg_color=BG_INPUT, border_color=BORDER,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            width=320, height=34, corner_radius=4, text_color=TEXT,
        )
        if self._settings.output_folder:
            self._folder_entry.insert(0, self._settings.output_folder)
        self._folder_entry.configure(state="readonly")
        self._folder_entry.pack(side="left")
        ctk.CTkButton(
            r, text="Browse…", width=88, height=34,
            fg_color=BTN_SEC_BG, hover_color=BTN_SEC_HV, text_color=BTN_SEC_TXT,
            border_width=1, border_color=BTN_SEC_BORDER,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_SM),
            corner_radius=4, cursor="arrow",
            command=self._browse_folder,
        ).pack(side="left", padx=(6, 0))

        r2 = _row(card.body, "Narration WPM")
        self._wpm_slider = ctk.CTkSlider(
            r2, from_=80, to=220,
            button_color=ACCENT, button_hover_color=ACCENT_DARK,
            progress_color=ACCENT, fg_color=BORDER,
            width=280, height=16, corner_radius=4,
            cursor="arrow",
        )
        self._wpm_slider.set(self._settings.wpm)
        self._wpm_slider.pack(side="left", padx=(0, 12))
        self._wpm_label = ctk.CTkLabel(
            r2, text=f"{int(self._settings.wpm)} WPM", width=72,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD, weight="bold"),
            text_color=ACCENT, anchor="w",
        )
        self._wpm_label.pack(side="left")
        self._wpm_slider.configure(
            command=lambda v: self._wpm_label.configure(text=f"{int(v)} WPM"),
        )

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color=BG_PANEL, height=60)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        inner = ctk.CTkFrame(footer, fg_color="transparent")
        inner.place(relx=1.0, rely=0.5, anchor="e", x=-20)
        ctk.CTkButton(
            inner, text="Cancel", width=110,
            fg_color=BTN_SEC_BG, hover_color=BTN_SEC_HV, text_color=BTN_SEC_TXT,
            border_width=1, border_color=BTN_SEC_BORDER,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD),
            corner_radius=4, cursor="arrow",
            command=self._cancel,
        ).pack(side="left", padx=(0, 8))
        self._save_btn = ctk.CTkButton(
            inner, text="Save Settings", width=130,
            fg_color=BTN_PRIMARY_BG, hover_color=BTN_PRIMARY_HV, text_color=BTN_PRIMARY_TXT,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_MD, weight="bold"),
            corner_radius=4, cursor="arrow",
            command=self._save,
        )
        self._save_btn.pack(side="left")

    def _browse_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Select Output Folder")
        if chosen:
            self._folder_entry.configure(state="normal")
            self._folder_entry.delete(0, "end")
            self._folder_entry.insert(0, chosen)
            self._folder_entry.configure(state="readonly")

    def _cancel(self) -> None:
        from docu_studio.gui.screens.main_screen import MainScreen
        self._app.show_screen(MainScreen(self._app))

    def _save(self) -> None:
        self._save_btn.configure(text="Saving…", state="disabled")

        provider = self._llm_provider_menu.get()
        llm_key = self._llm_key_entry.get().strip()
        el_key = self._el_key.get().strip()
        dg_key = self._dg_key.get().strip()
        pexels_key = self._pexels_key_entry.get().strip()
        pixabay_key = self._pixabay_key_entry.get().strip()
        serper_key = self._serper_key_entry.get().strip()
        footage = [p for p in ("pexels", "pixabay") if self._footage_enabled.get(p)]
        wpm = int(self._wpm_slider.get())
        output_folder = self._folder_entry.get().strip() or None
        llm_model = self._llm_model_menu.get()
        dg_voice = self._dg_voice.get()
        keyring_name = _PROVIDER_KEYRING.get(provider, "")
        prior = self._settings

        def _do_save() -> None:
            if keyring_name:
                key_cache.set_key(keyring_name, llm_key)
            key_cache.set_key("elevenlabs", el_key)
            key_cache.set_key("docu_studio_deepgram_key", dg_key)
            key_cache.set_key("pexels", pexels_key)
            key_cache.set_key("pixabay", pixabay_key)
            key_cache.set_key("serper", serper_key)
            settings = Settings(
                wpm=wpm,
                tts_provider=self._tts_var,
                footage_providers=footage,
                llm_model_script=prior.llm_model_script,
                llm_model_keywords=prior.llm_model_keywords,
                output_folder=output_folder,
                llm_provider=provider,
                llm_model=llm_model,
                deepgram_voice=dg_voice,
            )
            settings.save()
            self._settings = settings
            self.after(0, lambda: self._save_btn.configure(
                text="✓ Saved", fg_color=SUCCESS, state="normal",
            ))
            self.after(1800, lambda: self._save_btn.configure(
                text="Save Settings", fg_color=BTN_PRIMARY_BG,
            ))

        threading.Thread(target=_do_save, daemon=True).start()
