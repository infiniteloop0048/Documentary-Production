"""Design tokens — Slate Pro dark system for Documentary Studio.

No tkinter import at module level — importable in headless test environments.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import customtkinter as ctk

# ── Backgrounds ───────────────────────────────────────────────────────────────
BG_APP:   Final[str] = "#0f172a"   # near-black app background
BG_PANEL: Final[str] = "#1e293b"   # elevated panel / sidebar
BG_CARD:  Final[str] = "#1e293b"   # card surface
BG_INPUT: Final[str] = "#0f172a"   # input field fill
BG_HOVER: Final[str] = "#334155"   # hover / pending pill

# ── Borders ───────────────────────────────────────────────────────────────────
BORDER:        Final[str] = "#334155"
BORDER_STRONG: Final[str] = "#475569"

# ── Text ──────────────────────────────────────────────────────────────────────
TEXT:       Final[str] = "#ffffff"   # primary text
TEXT_DIM:   Final[str] = "#b0b8d0"   # secondary / muted text
TEXT_FAINT: Final[str] = "#7a8099"   # disabled / placeholder text

# ── Accent (sky-cyan) ─────────────────────────────────────────────────────────
ACCENT:      Final[str] = "#38bdf8"
ACCENT_DARK: Final[str] = "#0284c7"
ACCENT_TINT: Final[str] = "#0c4a6e"

# ── Semantic ──────────────────────────────────────────────────────────────────
SUCCESS: Final[str] = "#4ade80"
WARNING: Final[str] = "#fbbf24"
ERROR:   Final[str] = "#f87171"
INFO:    Final[str] = "#38bdf8"

# ── Section accent strips ─────────────────────────────────────────────────────
SECTION_TTS:     Final[str] = "#a855f7"   # purple  — TTS card
SECTION_FOOTAGE: Final[str] = "#4ade80"   # green   — Footage card
SECTION_TOPIC:   Final[str] = "#fb923c"   # orange  — Topic card

# ── Button: Primary ───────────────────────────────────────────────────────────
BTN_PRIMARY_BG:  Final[str] = "#38bdf8"
BTN_PRIMARY_HV:  Final[str] = "#0284c7"
BTN_PRIMARY_TXT: Final[str] = "#0f172a"

# ── Button: Secondary ─────────────────────────────────────────────────────────
BTN_SEC_BG:     Final[str] = "#1e293b"
BTN_SEC_HV:     Final[str] = "#334155"
BTN_SEC_TXT:    Final[str] = "#94a3b8"
BTN_SEC_BORDER: Final[str] = "#334155"


# ── Typography ────────────────────────────────────────────────────────────────

def _pick_font(candidates: list[str], fallback: str) -> str:
    """Return first candidate present on the system; fall back to fallback."""
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        root = tk._default_root  # type: ignore[attr-defined]
        if root is None:
            return candidates[0]
        available = frozenset(tkfont.families(root))
        for f in candidates:
            if f in available:
                return f
    except Exception:
        pass
    return fallback


if sys.platform == "darwin":
    FONT_UI   = _pick_font(["SF Pro Display", "Helvetica Neue", "Helvetica"], "Helvetica")
    FONT_MONO = _pick_font(["SF Mono", "Menlo", "Monaco"], "Monaco")
elif sys.platform == "win32":
    FONT_UI   = _pick_font(["Segoe UI", "Calibri", "Arial"], "Arial")
    FONT_MONO = _pick_font(["Consolas", "Lucida Console", "Courier New"], "Courier New")
else:
    FONT_UI   = _pick_font(["DejaVu Sans", "Noto Sans", "Ubuntu", "Liberation Sans"], "DejaVu Sans")
    FONT_MONO = _pick_font(["DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono"], "DejaVu Sans Mono")


# ── Size scale ────────────────────────────────────────────────────────────────
SZ_XS:  Final[int] = 12
SZ_SM:  Final[int] = 13
SZ_MD:  Final[int] = 15
SZ_LG:  Final[int] = 17
SZ_XL:  Final[int] = 21
SZ_2XL: Final[int] = 25
SZ_3XL: Final[int] = 31

# ── Animation ─────────────────────────────────────────────────────────────────
ANIM_STAGE_MS: Final[int] = 400
ANIM_STEPS:    Final[int] = 20

# ── Pipeline stage names ──────────────────────────────────────────────────────
STAGE_NAMES: list[str] = ["Research", "Script", "Voice", "Footage", "Render"]

# ── Backward-compat aliases (app.py and legacy code use these names) ──────────
COLOR_PITCH:         Final[str] = BG_APP
COLOR_BOND:          Final[str] = TEXT
COLOR_HALIDE:        Final[str] = WARNING
COLOR_GRADE:         Final[str] = TEXT_DIM
COLOR_CUE:           Final[str] = ERROR
COLOR_PITCH_SURFACE: Final[str] = BG_CARD
COLOR_PITCH_MID:     Final[str] = BG_PANEL
COLOR_HALIDE_HOVER:  Final[str] = ACCENT_DARK


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_display_family() -> str:
    return FONT_UI


def get_body_family() -> str:
    return FONT_UI


def font(
    size: int = SZ_MD,
    weight: str = "normal",
    mono: bool = False,
) -> "ctk.CTkFont":
    import customtkinter as ctk
    family = FONT_MONO if mono else FONT_UI
    return ctk.CTkFont(family=family, size=size, weight=weight)


def resolve_font(chain: list[str], available: frozenset[str] | None = None) -> str:
    """Return first font in *chain* available on the system; fall back to last."""
    if available is None:
        return chain[0]
    for f in chain:
        if f in available:
            return f
    return chain[-1]
