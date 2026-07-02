# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Windows build of Documentary Pre-Production Studio.

Must be built ON WINDOWS (PyInstaller does not cross-compile). Build with:
    pyinstaller docu_studio.spec

See docs/notes near the bottom of this repo's packaging report for the full
build procedure, including how to source ffprobe.exe before running this.

Entry point: docu_studio/__main__.py -> docu_studio.gui.webview_app.run()
This is the pywebview-based UI (NOT the legacy customtkinter gui/app.py,
which is unreachable from this entry point and intentionally excluded below).
"""
from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

block_cipher = None

PROJECT_ROOT = Path(SPECPATH)  # noqa: F821 -- SPECPATH is injected by PyInstaller
WEB_DIR = PROJECT_ROOT / "docu_studio" / "gui" / "web"

# --- datas -------------------------------------------------------------
# 1. Static web UI assets loaded by webview_app.py via
#    Path(__file__).parent / "web" -- must land at the same relative path
#    (docu_studio/gui/web) inside the bundle for that lookup to work unchanged.
datas = [
    (str(WEB_DIR / "index.html"), "docu_studio/gui/web"),
    (str(WEB_DIR / "app.js"), "docu_studio/gui/web"),
    (str(WEB_DIR / "tailwind.js"), "docu_studio/gui/web"),
]

# 2. imageio-ffmpeg ships its ffmpeg.exe as in-package data (not a normal
#    Python import), so it has to be explicitly collected. This walks
#    imageio_ffmpeg/binaries/ and pulls in whatever is physically present
#    at build time on the Windows machine -- which must include BOTH:
#      - ffmpeg-win-x86_64-v7.1.exe  (installed automatically by `pip install
#        imageio-ffmpeg` on Windows -- no action needed)
#      - ffprobe.exe                 (NOT shipped by imageio-ffmpeg; you must
#        manually copy a Windows ffprobe.exe into
#        .venv\\Lib\\site-packages\\imageio_ffmpeg\\binaries\\ffprobe.exe
#        BEFORE running pyinstaller -- see build commands)
# This preserves the package-relative path so platform_layer.ffprobe_exe()'s
# "bundled path next to ffmpeg" check finds it with zero code changes.
datas += collect_data_files("imageio_ffmpeg")

# 3. keyring's backend auto-discovery reads its own entry_points.txt via
#    importlib.metadata at runtime. PyInstaller does not bundle .dist-info
#    metadata by default, so without this, entry-point discovery returns
#    nothing and keyring silently falls back to backends.fail.Keyring --
#    every settings/API-key read and write then fails silently (key_cache.py
#    swallows the exception). This is the single most important line in
#    this spec file.
datas += copy_metadata("keyring")

# --- hiddenimports -------------------------------------------------------
# keyring backends are selected via importlib.metadata entry points (a
# string-based lookup PyInstaller's static analysis cannot see), so the
# concrete backend module has to be listed explicitly. Windows is the only
# backend this build needs; chainer/fail are keyring's own internal
# fallbacks and are cheap to include for safety.
hiddenimports = [
    "keyring.backends.Windows",
    "keyring.backends.chainer",
    "keyring.backends.fail",
]
# NOTE: LLM/TTS/footage provider adapters (anthropic_adapter, openai_adapter,
# openrouter_adapter, groq_adapter, gtts_adapter, elevenlabs_adapter,
# deepgram_adapter, pexels_adapter, pixabay_adapter, coverr_adapter) are all
# loaded via plain `from module import Name` statements inside
# adapters/*/factory.py -- PyInstaller's AST-based import scanner follows
# those even though they're inside function bodies, so they do NOT need to
# be listed here. Same for pywebview's platform backend selection
# (webview.platforms.qt etc. in guilib.py) -- also plain imports, and
# pywebview ships its own PyInstaller hook (webview/__pyinstaller/) that
# PyInstaller auto-discovers for its data/binary files.

# --- excludes --------------------------------------------------------
# pyproject.toml pulls in BOTH the PyQt5 and PyQt6 stacks (plus their
# WebEngine variants), but webview_app.py unconditionally forces
# QT_API=pyqt5 / PYWEBVIEW_GUI=qt before webview is imported, so PyQt6 is
# never reachable at runtime. Excluding it avoids bundling a second full
# QtWebEngine/Chromium payload (very large) and avoids qtpy binding
# ambiguity. customtkinter/PIL are excluded because gui/app.py (the legacy
# Tk-based screens) is unreachable from this entry point.
excludes = [
    "PyQt6",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineQuick",
    "PySide2",
    "PySide6",
    "customtkinter",
]

a = Analysis(
    [str(PROJECT_ROOT / "docu_studio" / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --onedir (via EXE(exclude_binaries=True) + COLLECT below), not --onefile:
# QtWebEngine bundles a full Chromium payload (100s of MB) plus ffmpeg.exe
# and ffprobe.exe as external subprocess binaries. --onefile would
# re-extract all of that to a fresh %TEMP%\_MEIxxxxxx directory on every
# launch (slow startup, disk churn, AV false positives, and a harder-to
# -debug "did ffprobe.exe actually land next to ffmpeg.exe" question). With
# --onedir the extracted tree is inspectable directly under dist/DocuStudio/,
# which matters a lot for a first Windows build where several pieces above
# (keyring metadata, ffprobe placement, QtWebEngine resources) are untested.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DocuStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,  # place an .ico under e.g. packaging/docu_studio.ico and point here if wanted
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="DocuStudio",
)
