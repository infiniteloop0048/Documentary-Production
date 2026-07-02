"""Theme application for Documentary Pre-Production Studio.

Call apply_theme() once before creating any CTk widgets — it sets dark mode
and applies the built-in dark-blue color theme.

display_font() and body_font() are kept for backward compatibility; new code
should call font() from tokens.py directly.
"""
from __future__ import annotations


def apply_theme() -> None:
    """Set appearance mode and color theme. Must be called before any CTk widget."""
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


def display_font(size: int = 22, weight: str = "bold") -> "ctk.CTkFont":  # type: ignore[name-defined]
    """Backward-compat wrapper — delegates to tokens.font()."""
    from docu_studio.gui.tokens import font as _font
    return _font(size=size, weight=weight)


def body_font(size: int = 14, weight: str = "normal") -> "ctk.CTkFont":  # type: ignore[name-defined]
    """Backward-compat wrapper — delegates to tokens.font()."""
    from docu_studio.gui.tokens import font as _font
    return _font(size=size, weight=weight)
