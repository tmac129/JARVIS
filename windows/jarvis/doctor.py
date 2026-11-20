"""`jarvis doctor`: controlla l'installazione e stampa un report da incollare in una issue o in chat.

Il report non contiene password, token ne' testo dei tuoi dati: solo versioni, presenza di componenti e
l'esito di piccole prove di sola lettura. Il nome utente nei percorsi viene sostituito da "~".
"""
from __future__ import annotations

import importlib
import os
import platform
import shutil
from pathlib import Path

from .core import IS_WINDOWS, Paths

OK, WARN, ERR = "[OK]", "[DA VEDERE]", "[ERRORE]"


def _hide_home(s: str) -> str:
    home = str(Path.home())
    return s.replace(home, "~") if home else s


class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.errors = 0
        self.warnings = 0

    def add(self, level: str, name: str, detail: str = "") -> None:
        if level == ERR:
            self.errors += 1
        elif level == WARN:
            self.warnings += 1
        self.lines.append(f"{level:<12} {name}" + (f": {_hide_home(detail)}" if detail else ""))

    def check(self, name: str, fn, level_on_fail: str = ERR) -> None:
        """Esegue fn(): se restituisce (livello, dettaglio) lo usa, se lancia un errore lo segnala."""
        try:
            r = fn()
        except Exception as e:  # il report non deve mai interrompersi
            self.add(level_on_fail, name, f"{type(e).__name__}: {e}")
            return
        if isinstance(r, tuple):
            self.add(r[0], name, r[1])
        else:
            self.add(OK, name, r or "")


def _import(mod: str) -> tuple[str, str]:
    m = importlib.import_module(mod)
    return OK, getattr(m, "__version__", "") or ""


def run_doctor() -> int:
    r = Report()
    r.add(OK, "Python", f"{platform.python_version()} ({platform.machine()})")
    r.add(OK if IS_WINDOWS else WARN, "Sistema", f"{platform.system()} {platform.release()} {platform.version()}"
          + ("" if IS_WINDOWS else " (non e' Windows: le prove di sistema vengono saltate)"))
    from . import __version__
    r.add(OK, "JARVIS", __version__)
    r.add(OK, "Cartella dati", str(Paths.support))

    # --- Claude Code
    from .bridge import ClaudeSession
    claude = ClaudeSession.claude_path()
    if not claude:
        r.add(ERR, "Claude Code", "non trovato (installalo con il comando del README, poi riapri il terminale)")
    else:
        r.add(OK, "Claude Code", claude)
        r.check("Versione Claude Code", lambda: (OK, __import__("subprocess").run(
            [claude, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()))
        installed, logged, plan = ClaudeSession.account_status()
        r.add(OK if logged else ERR, "Account Claude", f"collegato ({plan or 'piano non indicato'})" if logged
              else "non collegato: esegui `claude auth login`")

    # --- Git Bash (serve a Claude Code su Windows)
    def git_bash():
        cands = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), shutil.which("bash"),
                 r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"]
        found = next((c for c in cands if c and Path(c).exists()), None)
        return (OK, found) if found else (ERR if IS_WINDOWS else WARN, "Git for Windows non trovato")
    r.check("Git Bash", git_bash)

    # --- comando jarvis nel PATH di Claude
    def jarvis_cmd():
        d = Paths.tool_dir()
        return (OK, d) if any((Path(d) / n).exists() for n in ("jarvis.exe", "jarvis.cmd", "jarvis")) \
            else (ERR, f"comando `jarvis` non trovato in {d}: reinstalla con `pip install -r requirements.txt`")
    r.check("Comando jarvis", jarvis_cmd)

    # --- librerie
    for label, mod, win_only in [
        ("Libreria Google", "googleapiclient", False), ("Libreria pywebview", "webview", False),
        ("Libreria pystray", "pystray", False), ("Libreria psutil", "psutil", False),
        ("Libreria Pillow", "PIL", False), ("Libreria pypdf", "pypdf", False), ("Libreria python-docx", "docx", False),
        ("Libreria send2trash", "send2trash", False), ("Libreria keyboard", "keyboard", False),
        ("Libreria sounddevice", "sounddevice", False), ("Libreria vosk", "vosk", False),
        ("Libreria pycaw (volume)", "pycaw", True), ("Libreria screen-brightness-control", "screen_brightness_control", True),
        ("Libreria pywin32 (voce)", "win32com", True),
    ]:
        if win_only and not IS_WINDOWS:
            continue
        r.check(label, lambda m=mod: _import(m))

    # --- Google
    from .google_auth import CLIENT_FILE, TOKEN_FILE
    r.add(OK if Paths.file(CLIENT_FILE).exists() else WARN, "Credenziali Google (google_client.json)",
          "presenti" if Paths.file(CLIENT_FILE).exists() else "mancanti (servono per Calendario, Promemoria, Mail, Contatti)")
    r.add(OK if Paths.file(TOKEN_FILE).exists() else WARN, "Account Google collegato",
          "si" if Paths.file(TOKEN_FILE).exists() else "no: `jarvis google login`")

    # --- voce
    from .app.voice import find_model
    m = find_model()
    r.add(OK if m else WARN, "Modello vocale italiano", m or "mancante: `jarvis setup-voice` (solo per i comandi a voce)")

    if IS_WINDOWS:
        _windows_checks(r)

    print("J.A.R.V.I.S. doctor\n" + "-" * 60)
    print("\n".join(r.lines))
    print("-" * 60)
    print(f"{r.errors} errori, {r.warnings} da vedere. Incolla tutto questo testo quando segnali un problema.")
    return 1 if r.errors else 0


def _windows_checks(r: Report) -> None:
    import winreg

    def webview2():
        for root, sub in [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                          (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")]:
            try:
                with winreg.OpenKey(root, sub) as k:
                    return OK, winreg.QueryValueEx(k, "pv")[0]
            except OSError:
                continue
        return ERR, "WebView2 Runtime non trovato: installalo da Microsoft (serve alla finestra del HUD)"
    r.check("WebView2 Runtime", webview2)

    from .tools import system as sysmod

    def volume():
        out = sysmod.volume("")
        return OK, out
    r.check("Prova volume (lettura)", volume, WARN)

    def brightness():
        import screen_brightness_control as sbc
        v = sbc.get_brightness()
        return (OK, f"{v}") if v else (WARN, "nessuno schermo regolabile")
    r.check("Prova luminosita' (lettura)", brightness, WARN)

    def battery():
        import psutil
        b = psutil.sensors_battery()
        return (OK, f"{round(b.percent)}%") if b else (OK, "nessuna batteria (PC fisso)")
    r.check("Prova batteria", battery, WARN)

    def apps():
        a = sysmod.start_apps(refresh=True)
        return (OK, f"{len(a)} app nel Menu Start") if a else (WARN, "nessuna app trovata nel Menu Start")
    r.check("App del Menu Start", apps, WARN)

    def windows():
        names = sysmod.open_windows()
        return OK, f"{len(names)} finestre visibili"
    r.check("Prova elenco finestre", windows, WARN)

    def schtasks():
        from .core import run_process
        res = run_process(["schtasks.exe", "/Query", "/FO", "LIST"], timeout=30)
        return (OK, "disponibile") if res.code == 0 else (ERR, res.err or "non risponde")
    r.check("Utilita' di pianificazione (sveglie)", schtasks)

    def mic():
        import sounddevice as sd
        n = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        return (OK, f"{len(n)} ingressi audio") if n else (WARN, "nessun microfono trovato")
    r.check("Microfono", mic, WARN)

    def privacy(fn):
        def check():
            p = fn()
            return (OK if p.ok else WARN, p.detail + ("" if p.ok or not p.settings else f" (apri {p.settings})"))
        return check
    from . import permissions
    r.check("Permesso microfono", privacy(permissions.microphone), WARN)
    r.check("Notifiche", privacy(permissions.notifications), WARN)

    def tts():
        import pythoncom
        from .speech import Speaker
        pythoncom.CoInitialize()
        voices = Speaker().voices()
        if not voices:
            return WARN, "nessuna voce SAPI trovata"
        return OK, "voci disponibili: " + "; ".join(v[1] for v in voices[:4]) + " (se non ce n'e' una italiana, aggiungi la lingua italiana a Windows)"
    r.check("Voce in uscita (SAPI)", tts, WARN)

    def spotify():
        apps = [a[0] for a in sysmod.start_apps()]
        return (OK, "installato") if any("spotify" in a.lower() for a in apps) else (WARN, "non installato (serve solo per cercare brani per nome)")
    r.check("Spotify", spotify, WARN)

    def hotkeys():
        importlib.import_module("keyboard")
        return OK, "libreria caricata (le scorciatoie si provano avviando jarvis-hud)"
    r.check("Scorciatoie globali", hotkeys, WARN)
