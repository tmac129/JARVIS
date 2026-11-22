"""Fondamenta condivise: percorsi, stato su file, riferimenti [e1], log azioni, argomenti, date, processi.

Equivalente di Util.swift della versione macOS. Nessuna dipendenza specifica di Windows qui dentro,
cosi' il modulo si importa e si prova anche su altri sistemi.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


class ToolError(Exception):
    """Errore atteso di uno strumento: il messaggio viene mostrato all'utente e al modello."""


# ----------------------------------------------------------------------------- percorsi

def _support_dir() -> Path:
    override = os.environ.get("JARVIS_HOME")
    if override:
        base = Path(override)
    elif IS_WINDOWS and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "JARVIS"
    else:
        base = Path.home() / ".jarvis"
    base.mkdir(parents=True, exist_ok=True)
    return base


class Paths:
    support: Path = _support_dir()

    @staticmethod
    def file(name: str) -> Path:
        return Paths.support / name

    @staticmethod
    def home() -> Path:
        return Path.home()

    @staticmethod
    def known_folder(name: str) -> Path:
        """Desktop / Documents / Downloads / Pictures: segue il reindirizzamento OneDrive se presente."""
        if IS_WINDOWS:
            try:
                from . import winapi
                p = winapi.known_folder(name)
                if p:
                    return Path(p)
            except Exception:
                pass
        return Path.home() / name

    @staticmethod
    def expand(p: str) -> str:
        s = p.strip().strip('"')
        low = s.replace("\\", "/")
        for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
            for pref in (f"~/{name}", f"~\\{name}"):
                if low == pref.replace("\\", "/") or low.startswith(pref.replace("\\", "/") + "/"):
                    rest = low[len(pref):].lstrip("/")
                    base = Paths.known_folder(name)
                    return os.path.normpath(str(base / rest) if rest else str(base))
        if s.startswith("~"):
            s = os.path.expanduser(s)
        s = os.path.expandvars(s) if IS_WINDOWS else s
        if not os.path.isabs(s):
            s = str(Path.home() / s)
        return os.path.normpath(s)

    @staticmethod
    def pretty(p: str) -> str:
        home = str(Path.home())
        return "~" + p[len(home):].replace("\\", "/") if p.startswith(home) else p

    @staticmethod
    def command() -> list[str]:
        """Comando per rilanciare il CLI `jarvis` (timer, sveglie): finestra nascosta su Windows."""
        exe = Path(sys.executable)
        if IS_WINDOWS:
            pyw = exe.with_name("pythonw.exe")
            exe = pyw if pyw.exists() else exe
        return [str(exe), "-m", "jarvis"]

    @staticmethod
    def tool_dir() -> str:
        """Cartella da mettere nel PATH di Claude: contiene il comando `jarvis`."""
        scripts = Path(sys.executable).parent
        names = ("jarvis.exe", "jarvis.cmd", "jarvis") if IS_WINDOWS else ("jarvis",)
        for d in (scripts, scripts / "Scripts"):
            if any((d / n).exists() for n in names):
                return str(d)
        found = shutil.which("jarvis")
        return str(Path(found).parent) if found else str(scripts)


# ----------------------------------------------------------------------------- stato JSON

_io_lock = threading.Lock()


class Store:
    @staticmethod
    def load(name: str, default=None):
        try:
            with open(Paths.file(name), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    @staticmethod
    def save(name: str, value) -> None:
        target = Paths.file(name)
        tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
        with _io_lock:
            try:
                tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
                os.replace(tmp, target)
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass


class Refs:
    """Riferimenti brevi ([e1], [m2], [f3]) agli elementi dell'ultimo elenco: meno token."""

    @staticmethod
    def assign(prefix: str, values: list[str]) -> list[str]:
        allr: dict = Store.load("refs.json", {}) or {}
        allr = {k: v for k, v in allr.items()
                if not (k.startswith(prefix) and k[len(prefix):].isdigit())}
        labels = []
        for i, v in enumerate(values):
            k = f"{prefix}{i + 1}"
            allr[k] = v
            labels.append(k)
        Store.save("refs.json", allr)
        return labels

    @staticmethod
    def resolve(s: str) -> str | None:
        k = s.strip("[] ")
        return (Store.load("refs.json", {}) or {}).get(k)


ACTION_LOG_MAX = 256 * 1024   # byte


class ActionLog:
    """Feed delle azioni (letto dal HUD): una riga JSON per evento."""

    @staticmethod
    def add(module: str, text: str) -> None:
        line = json.dumps({"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                           "module": module, "text": text}, ensure_ascii=False)
        path = Paths.file("actions.log")
        try:
            # rotazione: oltre ACTION_LOG_MAX il file diventa actions.log.1 (una sola copia precedente)
            if path.exists() and path.stat().st_size > ACTION_LOG_MAX:
                os.replace(path, path.with_name("actions.log.1"))
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ----------------------------------------------------------------------------- processi

@dataclass
class ProcResult:
    out: str
    err: str
    code: int


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def run_process(argv: list[str], stdin: str | None = None, timeout: float = 60, env: dict | None = None) -> ProcResult:
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, creationflags=_flags())
    except subprocess.TimeoutExpired:
        raise ToolError(f"{Path(argv[0]).name}: tempo scaduto")
    except OSError as e:
        raise ToolError(f"impossibile avviare {Path(argv[0]).name}: {e}")
    return ProcResult(r.stdout.strip(), r.stderr.strip(), r.returncode)


def powershell(script: str, timeout: float = 60) -> ProcResult:
    """Windows PowerShell 5.1 (presente su ogni Windows 10/11). I dati utente non vanno mai nello script."""
    prefix = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; "
    return run_process(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", prefix + script], timeout=timeout)


def spawn_detached(argv: list[str]) -> int:
    """Avvia un processo indipendente, che sopravvive al chiamante (e allo strumento Bash di Claude)."""
    kwargs: dict = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if IS_WINDOWS:
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **kwargs).pid
    except OSError as e:
        raise ToolError(f"impossibile avviare il processo ({e})")


# ----------------------------------------------------------------------------- argomenti

class Args:
    def __init__(self, a: list[str], flags: set[str] | None = None):
        self.pos: list[str] = []
        self.opts: dict[str, list[str]] = {}
        self.flags: set[str] = set()
        known = flags or set()
        i = 0
        while i < len(a):
            s = a[i]
            if s.startswith("--") and len(s) > 2:
                k = s[2:]
                if k in known or i + 1 >= len(a):
                    self.flags.add(k)
                else:
                    self.opts.setdefault(k, []).append(a[i + 1])
                    i += 1
            else:
                self.pos.append(s)
            i += 1

    def o(self, *keys: str) -> str | None:
        for k in keys:
            if self.opts.get(k):
                return self.opts[k][-1]
        return None

    def list(self, *keys: str) -> list[str]:
        out = []
        for k in keys:
            for v in self.opts.get(k, []):
                out += [x.strip() for x in v.split(",") if x.strip()]
        return out

    def has(self, k: str) -> bool:
        return k in self.flags


# ----------------------------------------------------------------------------- testo

def fold(s: str) -> str:
    """Minuscolo senza accenti: per confronti 'contiene' come fa il Mac (case e diacritic insensitive)."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def clip(s: str, n: int, tail: str = "...") -> str:
    return s if len(s) <= n else s[:n] + tail


# ----------------------------------------------------------------------------- date

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]

# giorno della settimana come Apple (domenica = 1) per coerenza con la versione macOS
_WEEKDAYS = {
    "domenica": 1, "lunedi": 2, "lunedì": 2, "martedi": 3, "martedì": 3, "mercoledi": 4, "mercoledì": 4,
    "giovedi": 5, "giovedì": 5, "venerdi": 6, "venerdì": 6, "sabato": 7,
    "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6, "saturday": 7,
}


def start_of_day(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


class When:
    @staticmethod
    def parse(text: str, future_only: bool = False):
        """'2026-11-18 16:00', '18/11 16:00', 'domani 16', '16:30', 'lunedì 9:00', 'oggi'.
        Restituisce (datetime, ha_orario) oppure None."""
        s = text.lower()
        s = re.sub(r"(\d)t(\d)", r"\1 \2", s)
        s = re.sub(r"\b(alle|ore|h)\b", " ", s)
        now = datetime.now()
        day = None
        hour = None
        minute = 0
        for tok in s.split():
            m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", tok)
            if m:
                try:
                    day = datetime(int(m[1]), int(m[2]), int(m[3]))
                except ValueError:
                    day = None
                continue
            m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", tok)
            if m:
                y = int(m[3]) if m[3] else now.year
                if y < 100:
                    y += 2000
                try:
                    day = datetime(y, int(m[2]), int(m[1]))
                except ValueError:
                    day = None
                continue
            m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", tok)
            if m and (day is not None or hour is None):
                hour = int(m[1])
                minute = int(m[2]) if m[2] else 0
                continue
            if tok in ("oggi", "today", "stasera", "stamattina"):
                day = start_of_day(now)
                if tok == "stasera" and hour is None:
                    hour = 20
            elif tok in ("domani", "tomorrow"):
                day = start_of_day(now) + timedelta(days=1)
            elif tok == "dopodomani":
                day = start_of_day(now) + timedelta(days=2)
            elif tok in _WEEKDAYS:
                today = (now.weekday() + 1) % 7 + 1   # lun=0 -> 2 ... dom=6 -> 1
                diff = (_WEEKDAYS[tok] - today + 7) % 7
                if diff == 0:
                    diff = 7
                day = start_of_day(now) + timedelta(days=diff)
        if day is None and hour is None:
            return None
        if hour is not None and (hour > 23 or minute > 59):
            return None
        base = day or start_of_day(now)
        d = base.replace(hour=hour or 0, minute=minute, second=0, microsecond=0)
        if future_only and day is None and d <= now:
            d += timedelta(days=1)
        return d, hour is not None

    @staticmethod
    def duration(text: str):
        """'20m', '90s', '1h30m', '20', '20 minuti', '1 ora' -> secondi."""
        s = text.lower().replace(" ", "")
        try:
            return float(s) * 60
        except ValueError:
            pass
        total, found = 0.0, False
        for m in re.finditer(r"(\d+(?:[.,]\d+)?)(ore|ora|h|minuti|minuto|min|m|secondi|secondo|sec|s)", s):
            v = float(m[1].replace(",", "."))
            u = m[2]
            if u in ("ore", "ora", "h"):
                total += v * 3600
            elif u in ("secondi", "secondo", "sec", "s"):
                total += v
            else:
                total += v * 60
            found = True
        return total if found and total > 0 else None

    @staticmethod
    def fmt(d: datetime, time_: bool = True) -> str:
        base = f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]}"
        return f"{base} {d:%H:%M}" if time_ else base

    @staticmethod
    def hm(d: datetime) -> str:
        return f"{d:%H:%M}"

    @staticmethod
    def duration_text(secs: float) -> str:
        t = round(secs)
        h, m, s = t // 3600, (t % 3600) // 60, t % 60
        parts = []
        if h > 0:
            parts.append("1 ora" if h == 1 else f"{h} ore")
        if m > 0:
            parts.append("1 minuto" if m == 1 else f"{m} minuti")
        if s > 0:
            parts.append("1 secondo" if s == 1 else f"{s} secondi")
        return " e ".join(parts)


def now_ts() -> float:
    return time.time()
