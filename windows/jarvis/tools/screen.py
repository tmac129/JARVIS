"""Schermo: cattura la finestra che l'utente stava guardando prima di aprire JARVIS (o tutto lo schermo)."""
from __future__ import annotations

import time

from ..core import IS_WINDOWS, ActionLog, Args, Store, ToolError
from .docs import view_dir


def _front_window() -> tuple[int, str] | None:
    """Ultima finestra attiva diversa da JARVIS (la scrive il HUD in frontmost.json); altrimenti quella attiva ora."""
    from .. import winapi
    st = Store.load("frontmost.json", {}) or {}
    hwnd = st.get("hwnd")
    if hwnd and winapi.is_window(hwnd):
        return hwnd, st.get("name") or winapi.window_title(hwnd)
    fg = winapi.foreground_window()
    return (fg[0], fg[1]) if fg else None


def run(a: list[str]) -> str:
    if not IS_WINDOWS:
        raise ToolError("la cattura dello schermo richiede Windows")
    args = Args(a, flags={"full", "tutto"})
    try:
        from PIL import ImageGrab
    except ImportError:
        raise ToolError("libreria Pillow mancante: esegui `pip install -e .`")
    from .. import winapi
    out = view_dir() / f"screen-{int(time.time())}.jpg"
    img, what = None, "schermo intero"
    if not (args.has("full") or args.has("tutto")):
        w = _front_window()
        if w:
            img = winapi.capture_window(w[0])
            if img is not None:
                what = f"finestra di {w[1]}"
    if img is None:
        img = ImageGrab.grab(all_screens=True).convert("RGB")
        what = "schermo intero"
    img.thumbnail((1600, 1600))
    img.save(out, "JPEG", quality=80)
    ActionLog.add("VISION", f"Acquisita {what}")
    return f"Acquisita {what}: {out}. Guardala con lo strumento Read e rispondi alla domanda dell'utente."
