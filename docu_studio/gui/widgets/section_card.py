"""SectionCard — card widget with accent top strip and title header."""
from __future__ import annotations

import customtkinter as ctk

from docu_studio.gui.tokens import ACCENT, BG_CARD, BORDER, FONT_UI, TEXT, SZ_LG, font


class SectionCard(ctk.CTkFrame):
    """Card with a 3 px accent strip at the top, a title row, and a body frame."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        title: str,
        icon: str = "",
        accent: str | None = None,
        **kw: object,
    ) -> None:
        super().__init__(
            parent,
            fg_color=BG_CARD,
            corner_radius=5,
            border_width=1,
            border_color=BORDER,
            **kw,
        )
        ctk.CTkFrame(self, fg_color=accent or ACCENT, height=3, corner_radius=0).pack(fill="x")
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkLabel(
            hdr, text=title,
            font=ctk.CTkFont(family=FONT_UI, size=SZ_LG, weight="bold"),
            text_color=TEXT,
        ).pack(side="left")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=18, pady=(8, 16))
