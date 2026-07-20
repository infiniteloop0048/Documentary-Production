from __future__ import annotations
import os, threading, sys, shutil, pathlib
from pathlib import Path

# Force Qt5 backend for pywebview (Qt6 requires libxcb-cursor0 system package)
os.environ.setdefault("QT_API", "pyqt5")
os.environ['PYWEBVIEW_GUI'] = 'qt'
os.environ.setdefault(
    'QTWEBENGINE_CHROMIUM_FLAGS',
    '--allow-file-access-from-files --disable-web-security'
)

import webview
from docu_studio.config import key_cache
from docu_studio.gui.bridge import Bridge

# Warm keyring immediately, in background
threading.Thread(target=key_cache.warm_cache, daemon=True).start()

WEB_DIR = Path(__file__).parent / "web"


def run():
    for cache in [
        pathlib.Path.home() / ".cache" / "pywebview",
        pathlib.Path.home() / ".cache" / "QtWebEngine",
        pathlib.Path.home() / ".local" / "share" / "pywebview",
    ]:
        if cache.exists():
            shutil.rmtree(cache)
            print(f"Cleared cache: {cache}")

    the_url = str(WEB_DIR / "index.html") + "?v=17"
    print("Loading URL:", the_url)

    bridge = Bridge()
    window = webview.create_window(
        title="Documentary Pre-Production Studio",
        url=the_url,
        js_api=bridge,
        width=1200,
        height=820,
        min_size=(960, 640),
        background_color="#111318",
        text_select=False,
    )
    bridge.set_window(window)
    webview.start(debug="--debug" in sys.argv, private_mode=False)
