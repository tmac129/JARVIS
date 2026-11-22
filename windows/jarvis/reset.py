"""`jarvis reset`: elimina tutto cio' che JARVIS ha salvato su questo PC.

Preferenze, moduli, log, cronologia, token Google, token del telefono, stato, sveglie
(Utilita' di pianificazione), timer in corso e avvio automatico. Solo da terminale interattivo:
mai dal modello, dal HUD o dal telefono.
"""
from __future__ import annotations

import shutil
import sys

from .core import IS_WINDOWS, Paths, Store

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def summary() -> str:
    alarms = Store.load("alarms.json", []) or []
    return (
        "Verranno eliminati:\n"
        f"  - la cartella dati {Paths.support}\n"
        "    (preferenze, moduli, log delle azioni e dei turni, token Google, token del telefono, stato)\n"
        f"  - {len(alarms)} sveglie nell'Utilità di pianificazione, i timer in corso e l'avvio automatico\n"
        "Restano: la cartella del programma, le note in Documenti\\JARVIS Note, l'accesso a Claude Code\n"
        "(claude auth logout) e l'autorizzazione Google (revocala da myaccount.google.com/permissions)."
    )


def run() -> str:
    from .tools import alarm
    alarms = Store.load("alarms.json", []) or []
    for a in alarms:
        alarm.remove(a.get("id", ""))
    for t in Store.load("timers.json", []) or []:
        try:
            import psutil
            psutil.Process(t["pid"]).terminate()
        except Exception:
            pass
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "JARVIS")
        except OSError:
            pass
    items = list(Paths.support.iterdir()) if Paths.support.exists() else []
    failed: list[str] = []
    for p in items:
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError:
            failed.append(p.name)
    try:
        Paths.support.rmdir()
    except OSError:
        pass
    out = f"Dati di JARVIS eliminati ({len(items)} file o cartelle, {len(alarms)} sveglie)."
    if failed:
        out += "\nNon eliminati (forse in uso: chiudi JARVIS e riprova): " + ", ".join(failed)
    return out


def interactive() -> int:
    if not sys.stdin.isatty():
        print("ERRORE: jarvis reset va eseguito da un terminale.")
        return 1
    print(summary())
    try:
        answer = input("Chiudi prima JARVIS dall'icona nella barra. Per procedere scrivi ELIMINA: ")
    except EOFError:
        answer = ""
    if answer.strip() != "ELIMINA":
        print("Annullato.")
        return 0
    print(run())
    return 0
