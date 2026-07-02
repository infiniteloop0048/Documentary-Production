"""DocsStudioApp — CustomTkinter root with screen stack navigation and queue polling."""
from __future__ import annotations

import os
import queue
import threading
from typing import TYPE_CHECKING

os.environ.setdefault("TK_SCALING", "1.0")

import customtkinter as ctk

ctk.set_widget_scaling(1.0)
ctk.set_window_scaling(1.0)

from docu_studio.config import key_cache
from docu_studio.gui.theme import apply_theme
from docu_studio.licensing import check_license
from docu_studio.pipeline.events import ErrorEvent, LogEvent, ProgressEvent

if TYPE_CHECKING:
    from docu_studio.gui.screens.main_screen import MainScreen

apply_theme()


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


def _patch_option_menu_cursor() -> None:
    """Monkey-patch CTkOptionMenu so every dropdown Toplevel gets cursor='arrow'."""
    try:
        from customtkinter import CTkOptionMenu
        if not hasattr(CTkOptionMenu, "_docustudio_patched"):
            original_open = CTkOptionMenu._open_dropdown_menu

            def _patched_open(self_widget, *args, **kwargs):  # type: ignore[no-untyped-def]
                original_open(self_widget, *args, **kwargs)
                try:
                    menu = getattr(self_widget, "_dropdown_menu", None)
                    if menu:
                        _fix_all_cursors(menu)
                except Exception:
                    pass

            CTkOptionMenu._open_dropdown_menu = _patched_open
            CTkOptionMenu._docustudio_patched = True
    except Exception:
        pass


class DocsStudioApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        try:
            _patch_option_menu_cursor()
        except Exception:
            pass
        self.title("Documentary Pre-Production Studio")
        self.geometry("1100x700")
        self.minsize(900, 600)

        threading.Thread(target=key_cache.warm_cache, daemon=True).start()

        if not check_license():
            self._show_license_error()
            return

        self._event_queue: queue.Queue | None = None
        self._active_screen: ctk.CTkFrame | None = None
        self._screen_cache: dict[type, ctk.CTkFrame] = {}

        from docu_studio.gui.screens.main_screen import MainScreen
        self.show_screen(MainScreen(self))
        self.after(100, self._poll_queue)

    def show_screen(self, screen: ctk.CTkFrame) -> None:
        screen_class = type(screen)
        cached = self._screen_cache.get(screen_class)
        if cached is not None and cached is not screen:
            screen.destroy()
            screen = cached
        else:
            self._screen_cache[screen_class] = screen
        if self._active_screen is not None:
            self._active_screen.pack_forget()
        self._active_screen = screen
        screen.pack(fill="both", expand=True)

    def attach_event_queue(self, q: queue.Queue) -> None:
        self._event_queue = q

    def detach_event_queue(self) -> None:
        self._event_queue = None

    def _poll_queue(self) -> None:
        if self._event_queue is not None:
            try:
                while True:
                    event = self._event_queue.get_nowait()
                    if self._active_screen and hasattr(self._active_screen, "handle_event"):
                        self._active_screen.handle_event(event)  # type: ignore[union-attr]
            except queue.Empty:
                pass
        self.after(100, self._poll_queue)

    def _show_license_error(self) -> None:
        from docu_studio.gui.theme import display_font
        from docu_studio.gui.tokens import COLOR_CUE
        label = ctk.CTkLabel(
            self, text="License check failed.",
            font=display_font(16), text_color=COLOR_CUE,
        )
        label.pack(expand=True)
