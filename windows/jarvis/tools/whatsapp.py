"""WhatsApp: invio tramite l'app desktop (whatsapp://send + Invio). Con conferma obbligatoria.

La LETTURA delle chat non e' supportata su Windows: WhatsApp per Windows non espone un database locale
leggibile come quello della versione per Mac. L'unica via ufficiale sarebbe la WhatsApp Business Cloud API
(richiede un account Business), non inclusa in questa versione.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse

from .. import gate
from ..core import IS_WINDOWS, ActionLog, Args, ToolError

_UNSUPPORTED = ("lettura delle chat WhatsApp non disponibile su Windows (WhatsApp per Windows non ha un database locale "
                "leggibile): posso solo inviare messaggi con `jarvis wa send`")


def normalize(p: str) -> str:
    d = re.sub(r"[^\d+]", "", p)
    if d.startswith("+"):
        d = d[1:]
    elif d.startswith("00"):
        d = d[2:]
    elif len(d) == 10 and d.startswith("3"):
        d = "39" + d
    return d


def resolve_recipient(to: str) -> tuple[str, str]:
    digits = re.sub(r"[^\d+]", "", to)
    if len(digits) >= 8 and len(digits) >= len(re.sub(r"\s", "", to)) - 1:
        return to, normalize(digits)
    from .mail import people_search
    from ..google_auth import call
    rows = call(lambda: people_search(to, limit=3))
    rows = [r for r in rows if r["phones"]]
    if not rows:
        raise ToolError(f'non trovo un numero WhatsApp per "{to}"')
    return rows[0]["name"], normalize(rows[0]["phones"][0])


def send(phone: str, name: str, text: str) -> str:
    if not IS_WINDOWS:
        raise ToolError("l'invio WhatsApp richiede Windows")
    from .. import winapi
    import psutil
    url = "whatsapp://send?" + urllib.parse.urlencode({"phone": phone, "text": text}, quote_via=urllib.parse.quote)
    try:
        os.startfile(url)  # type: ignore[attr-defined]
    except OSError:
        raise ToolError("WhatsApp per Windows non è installato (installalo dal Microsoft Store o da whatsapp.com)")
    time.sleep(3.0)
    fg = winapi.foreground_window()
    ok = False
    if fg:
        try:
            ok = "whatsapp" in psutil.Process(fg[2]).name().lower() or "whatsapp" in fg[1].lower()
        except psutil.Error:
            ok = "whatsapp" in fg[1].lower()
    if not ok:
        return f"Messaggio pronto in WhatsApp per {name}: premi Invio per mandarlo."
    try:
        import keyboard
        keyboard.send("enter")      # il tasto va solo a WhatsApp: mai premerlo in un'altra app
    except Exception:
        return f"Messaggio pronto in WhatsApp per {name}: premi Invio per mandarlo."
    ActionLog.add("WHATSAPP", f"Inviato a {name}: {text[:60]}")
    return f"Inviato su WhatsApp a {name}."


def run(a: list[str], confirmed: bool = False, raw: list[str] | None = None) -> str:
    sub = a[0] if a else "send"
    args = Args(a[1:])
    if sub in ("chats", "unread", "nonlette", "read", "leggi"):
        raise ToolError(_UNSUPPORTED)
    if sub in ("send", "invia"):
        to, text = args.o("to", "a"), args.o("text", "testo")
        if not to or not text:
            raise ToolError('uso: wa send --to <nome|numero> --text "messaggio"')
        name, phone = resolve_recipient(to)
        if not confirmed:
            return gate.request(f'Inviare su WhatsApp a {name}: "{text}"', raw or [])
        return send(phone, name, text)
    raise ToolError("uso: wa send --to <nome|numero> --text T")
