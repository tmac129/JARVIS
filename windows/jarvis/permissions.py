"""Permessi e configurazione di Windows usati da JARVIS: stato in sola lettura e pagina di Impostazioni da aprire.

Windows non ha permessi per app desktop come macOS (Accessibilita', Registrazione schermo): contano l'accesso
al microfono per le app desktop, le notifiche, le voci italiane, il modello vocale offline e gli account collegati.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .core import IS_WINDOWS, Paths

_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

VOICE_GUIDE = (
    "Voci italiane migliori su Windows: Impostazioni > Ora e lingua > Voce > Aggiungi voci, cerca Italiano e "
    "installalo (voci Elsa e Cosimo). Poi riapri il menu Voce di J.A.R.V.I.S. e scegli la nuova voce. "
    "Se non compare, riavvia J.A.R.V.I.S.")


@dataclass
class Permission:
    name: str
    ok: bool | None          # None = stato non leggibile
    detail: str
    settings: str | None     # pagina ms-settings: o None


def _reg_value(root, path: str, name: str):
    import winreg
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def microphone() -> Permission:
    """Il microfono serve sia acceso in generale sia per le app desktop (sottochiave NonPackaged)."""
    if not IS_WINDOWS:
        return Permission("Microfono", None, "solo Windows", None)
    import winreg
    states = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        states.append(_reg_value(root, _CONSENT, "Value"))
    states.append(_reg_value(winreg.HKEY_CURRENT_USER, _CONSENT + r"\NonPackaged", "Value"))
    if "Deny" in states:
        return Permission("Microfono", False, "bloccato nelle impostazioni privacy", "ms-settings:privacy-microphone")
    if any(s == "Allow" for s in states):
        return Permission("Microfono", True, "consentito", "ms-settings:privacy-microphone")
    return Permission("Microfono", None, "stato non leggibile", "ms-settings:privacy-microphone")


def notifications() -> Permission:
    if not IS_WINDOWS:
        return Permission("Notifiche", None, "solo Windows", None)
    import winreg
    v = _reg_value(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled")
    ok = v != 0
    return Permission("Notifiche", ok, "attive" if ok else "disattivate (niente avvisi di impegni e batteria)",
                      "ms-settings:notifications")


def voice_model() -> Permission:
    from .app.voice import find_model
    ok = find_model() is not None
    return Permission("Modello vocale italiano", ok, "presente" if ok else "mancante: esegui jarvis setup-voice", None)


def google() -> Permission:
    from .google_auth import TOKEN_FILE
    ok = Paths.file(TOKEN_FILE).exists()
    return Permission("Account Google", ok, "collegato" if ok else "non collegato (Mail, Calendario, Promemoria)", None)


def all_permissions() -> list[Permission]:
    out = []
    for fn in (microphone, notifications, voice_model, google):
        try:
            out.append(fn())
        except Exception as e:   # un controllo rotto non deve rompere il menu
            out.append(Permission(fn.__name__, None, f"errore: {type(e).__name__}", None))
    return out


def label(p: Permission) -> str:
    mark = {True: "OK", False: "DA ATTIVARE", None: "?"}[p.ok]
    return f"{p.name}: {mark}  ({p.detail})"


def open_settings(page: str) -> None:
    if IS_WINDOWS and page.startswith("ms-settings:"):
        os.startfile(page)  # type: ignore[attr-defined]
