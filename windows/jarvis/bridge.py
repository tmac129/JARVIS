"""Ponte verso Claude Code: un processo `claude -p` (stream-json) per livello di modello.

Sicurezza: Claude puo' eseguire SOLO `jarvis ...` (--allowedTools "Bash(jarvis:*)") e non puo' chiamare
`jarvis confirm` / `jarvis cancel`. Non allargare questi permessi.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import gate, prompt, turnlog
from .core import IS_WINDOWS, Paths, ToolError, When, run_process
from .router import Router, Tier


@dataclass
class TurnResult:
    text: str = ""
    tier: Tier = Tier.haiku
    is_error: bool = False
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    duration_ms: int = 0
    pending_confirm: str | None = None
    local: bool = False


@dataclass
class BridgeEvent:
    kind: str     # thinking | tool | toolResult | confirmNeeded | text | done
    value: object = None


def _env_int(key: str, default: int, minimum: int) -> int:
    try:
        v = int(os.environ.get(key, "").strip())
        return v if v >= minimum else default
    except ValueError:
        return default


class ClaudeSession:
    # Turni per processo prima del riavvio (contesto corto = meno token). Env: JARVIS_MAX_TURNS.
    max_turns = _env_int("JARVIS_MAX_TURNS", 8, 1)
    # Secondi di inattivita' dopo i quali il turno successivo riparte da zero. Env: JARVIS_IDLE_RESET.
    idle_reset = float(_env_int("JARVIS_IDLE_RESET", 600, 0))

    def __init__(self, tier: Tier, effort: str | None = None, vision: bool = False):
        self.tier = tier
        self.effort = effort or tier.effort
        # Le sessioni "vision" hanno anche lo strumento Read (per guardare le immagini).
        self.vision = vision
        self.session_id: str | None = None
        self.turns = 0
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._on_event = None
        self._current = TurnResult(tier=tier)
        self._started = time.time()
        self._last_use = time.time()
        self._last_total_cost = 0.0
        self._resolved_model: str | None = None

    # ---- ricerca di claude

    @staticmethod
    def claude_path() -> str | None:
        p = os.environ.get("JARVIS_CLAUDE")
        if p and Path(p).is_file():
            return p
        home = Path.home()
        cands = [home / ".local" / "bin" / "claude.exe", home / ".local" / "bin" / "claude",
                 home / ".claude" / "local" / "claude.exe", home / ".claude" / "local" / "claude"]
        for c in cands:
            if c.is_file():
                return str(c)
        return shutil.which("claude")

    @staticmethod
    def account_status() -> tuple[bool, bool, str | None]:
        """Stato del login di Claude Code (`claude auth status --json`). Sola lettura:
        JARVIS non fa mai il login da solo. Restituisce (installato, collegato, piano)."""
        claude = ClaudeSession.claude_path()
        if not claude:
            return False, False, None
        try:
            r = run_process([claude, "auth", "status", "--json"], timeout=15, env=ClaudeSession.clean_environment())
            o = json.loads(r.out)
        except (ToolError, ValueError):
            return True, False, None
        logged = bool(o.get("loggedIn", False))
        plan = o.get("subscriptionType") or o.get("planTier")
        if not plan and o.get("authMethod"):
            plan = "abbonamento" if "claude" in str(o["authMethod"]) else "console"
        return True, logged, plan

    @staticmethod
    def clean_environment() -> dict:
        env = dict(os.environ)
        # Se JARVIS parte da dentro di Claude Code, via le variabili della sessione ospite: il figlio deve usare il
        # login dell'utente. Nessuna chiave API. Eccezione: CLAUDE_CODE_GIT_BASH_PATH, che su Windows serve a
        # Claude Code per trovare Git Bash.
        for k in list(env):
            if k == "CLAUDE_CODE_GIT_BASH_PATH":
                continue
            if k.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK", "ANTHROPIC_")) or k == "CLAUDECODE":
                env.pop(k)
        env["PATH"] = Paths.tool_dir() + os.pathsep + env.get("PATH", "")
        env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"      # niente CLAUDE.md: meno token
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
        env["JARVIS_AGENT"] = "1"                        # `jarvis confirm` si rifiuta di girare per il modello
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    # ---- ciclo di vita

    @property
    def is_running(self) -> bool:
        p = self._proc
        return p is not None and p.poll() is None

    def start(self, resume: str | None = None) -> None:
        claude = self.claude_path()
        if not claude:
            raise ToolError("CLI claude non trovata: installala con il comando ufficiale e fai il login.")
        args = [
            claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", self.tier.model, "--effort", self.effort,
            "--system-prompt", prompt.system(),
            "--tools", os.environ.get("JARVIS_TOOLS") or ("Bash,Read" if self.vision else "Bash"),
            "--allowedTools", "Bash(jarvis:*)",
            "--disallowedTools", "Bash(jarvis confirm:*)", "Bash(jarvis cancel:*)",
            "--permission-mode", "dontAsk",
            "--strict-mcp-config",
        ]
        if resume:
            args += ["--resume", resume]
        try:
            proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self.clean_environment(), cwd=str(Paths.support), text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0)
        except OSError as e:
            raise ToolError(f"impossibile avviare claude: {e}")
        self._proc = proc
        self.turns = 0
        self._last_total_cost = 0.0
        self._resolved_model = None
        self._last_use = time.time()
        threading.Thread(target=self._read_stdout, args=(proc,), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            p, self._proc = self._proc, None
            self.session_id = None
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    # ---- invio

    def send(self, text: str, on_event) -> None:
        with self._lock:
            if self.is_running and (self.turns >= self.max_turns or time.time() - self._last_use > self.idle_reset):
                self.stop()
            try:
                if not self.is_running:
                    self.start()
            except ToolError as e:
                on_event(BridgeEvent("done", TurnResult(text=str(e), tier=self.tier, is_error=True)))
                return
            self._on_event = on_event
            self._current = TurnResult(tier=self.tier)
            self._started = time.time()
            self.turns += 1
            self._last_use = time.time()
            stamped = f"(ora attuale: {When.fmt(datetime.now())})\n{text}"
            msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": stamped}]}}
            on_event(BridgeEvent("thinking", self.tier))
            try:
                assert self._proc and self._proc.stdin
                self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError, AssertionError):
                # il processo claude e' morto tra un turno e l'altro: lo diciamo invece di andare in crash
                self._on_event = None
                self.stop()
                on_event(BridgeEvent("done", TurnResult(
                    text=f"Il modulo {self.tier.value} non risponde: riprova.", tier=self.tier, is_error=True)))

    def send_sync(self, text: str, timeout: float = 180, on_event=None) -> TurnResult:
        done = threading.Event()
        result = TurnResult(text="Timeout", tier=self.tier, is_error=True)

        def cb(ev: BridgeEvent):
            nonlocal result
            if on_event:
                on_event(ev)
            if ev.kind == "done":
                result = ev.value
                done.set()

        self.send(text, cb)
        done.wait(timeout)
        return result

    # ---- lettura dello stream-json

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stderr:
                if line.strip():
                    with open(Paths.file("claude.err.log"), "a", encoding="utf-8") as f:
                        f.write(line if line.endswith("\n") else line + "\n")
        except (OSError, ValueError):
            pass
        try:
            proc.stderr.close()
        except (OSError, ValueError, AttributeError):
            pass

    def _read_stdout(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                with self._lock:
                    if self._proc is proc:
                        self._handle(obj)
        except (OSError, ValueError):
            pass
        # fine dello stream: solo il processo attivo puo' chiudere un turno (uno vecchio, riciclato, no)
        proc.wait()
        for h in (proc.stdout, proc.stdin):
            try:
                h.close()
            except (OSError, ValueError, AttributeError):
                pass
        with self._lock:
            if self._proc is proc and self._on_event is not None:
                self._current.is_error = True
                if not self._current.text:
                    self._current.text = f"Il modulo {self.tier.value} si è interrotto (codice {proc.returncode})."
                self._finish()

    def _handle(self, o: dict) -> None:
        t = o.get("type")
        if o.get("session_id"):
            self.session_id = o["session_id"]
        ev = self._on_event
        if t == "system":
            if o.get("subtype") == "init" and o.get("model"):
                self._resolved_model = o["model"]
        elif t == "assistant":
            for b in (o.get("message") or {}).get("content") or []:
                if b.get("type") == "text" and b.get("text") and ev:
                    ev(BridgeEvent("text", b["text"]))
                if b.get("type") == "tool_use" and ev:
                    cmd = (b.get("input") or {}).get("command") or b.get("name") or ""
                    ev(BridgeEvent("tool", cmd))
        elif t == "user":
            for b in (o.get("message") or {}).get("content") or []:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                c = b.get("content")
                if isinstance(c, str):
                    text = c
                else:
                    text = "\n".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))
                if ev:
                    ev(BridgeEvent("toolResult", text))
                if gate.MARKER in text:
                    line = text[text.index(gate.MARKER):].split("\n", 1)[0]
                    self._current.pending_confirm = line
                    if ev:
                        ev(BridgeEvent("confirmNeeded", line))
        elif t == "result":
            cur = self._current
            cur.text = o.get("result") or cur.text
            # difesa: via un eventuale "(ora attuale: ...)" ripetuto, o un "[mar 17 nov 20:09]" iniziale
            cur.text = re.sub(r"\s*\(ora attuale:[^)]*\)\s*", " ", cur.text)
            cur.text = re.sub(r"^\s*\[[^\]]{3,30}\]\s*", "", cur.text).strip()
            cur.is_error = bool(o.get("is_error", False))
            total = o.get("total_cost_usd")
            total = float(total) if isinstance(total, (int, float)) else self._last_total_cost
            cur.cost_usd = max(0.0, total - self._last_total_cost)   # total_cost_usd e' cumulativo per processo
            self._last_total_cost = total
            cur.duration_ms = int(o.get("duration_ms") or (time.time() - self._started) * 1000)
            u = o.get("usage") or {}
            cur.input_tokens = int(u.get("input_tokens") or 0)
            cur.output_tokens = int(u.get("output_tokens") or 0)
            cur.cache_read = int(u.get("cache_read_input_tokens") or 0)
            cur.cache_write = int(u.get("cache_creation_input_tokens") or 0)
            self._finish()

    def _finish(self) -> None:
        cb, self._on_event = self._on_event, None
        if cb is not None:
            turnlog.record(self._current, self.tier.model, self._resolved_model, self.effort, self.vision,
                           self.turns, self.max_turns)
            cb(BridgeEvent("done", self._current))


class JarvisBrain:
    """Router + sessioni: l'API unica usata dal CLI e dal HUD."""

    EFFORTS = ["low", "medium", "high", "xhigh", "max"]

    def __init__(self, preferred_tier: Tier | None = None, effort: str | None = None):
        self._sessions: dict[str, ClaudeSession] = {}
        self._lock = threading.Lock()
        self._preferred = preferred_tier
        self._effort = effort
        self._outcome_note: str | None = None

    # nil = routing automatico (Haiku di default, salita per parole chiave)
    @property
    def preferred_tier(self) -> Tier | None:
        return self._preferred

    @preferred_tier.setter
    def preferred_tier(self, v: Tier | None) -> None:
        if v != self._preferred:
            self._preferred = v
            self.shutdown()
            self.prewarm()

    @property
    def effort(self) -> str | None:
        return self._effort

    @effort.setter
    def effort(self, v: str | None) -> None:
        if v != self._effort:
            self._effort = v
            self.shutdown()
            self.prewarm()

    @property
    def default_tier(self) -> Tier:
        return self._preferred or Tier.haiku

    @property
    def sessions(self) -> dict[str, ClaudeSession]:
        with self._lock:
            return dict(self._sessions)

    def note_outcome(self, s: str) -> None:
        self._outcome_note = s

    def session(self, tier: Tier, vision: bool = False) -> ClaudeSession:
        key = tier.value + ("+vision" if vision else "")
        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = ClaudeSession(tier, effort=self._effort, vision=vision)
            return self._sessions[key]

    def prewarm(self) -> None:
        """Avvia Haiku in anticipo: il primo comando non paga il tempo di avvio."""
        try:
            s = self.session(self.default_tier)
            if not s.is_running:
                s.start()
        except ToolError:
            pass

    def handle(self, text: str, on_event) -> None:
        from .cli import run
        route = Router.route(text, has_pending=gate.latest_id() is not None)
        # Sicurezza: un'azione critica si conferma solo col messaggio subito dopo. Qualsiasi altro comando
        # la scarta, cosi' un "si" successivo non conferma mai una richiesta vecchia.
        if not (route.kind == "local" and route.argv and route.argv[0] in ("confirm", "cancel")):
            gate.cancel_all()
        if route.kind == "answer":
            on_event(BridgeEvent("done", TurnResult(text=route.text, local=True)))
        elif route.kind == "local":
            out, code = run(route.argv)
            if route.argv[0] in ("confirm", "cancel"):
                self._outcome_note = out
            on_event(BridgeEvent("tool", "jarvis " + " ".join(route.argv)))
            r = TurnResult(text=route.reply or out, is_error=code != 0, local=True)
            if gate.MARKER in out:
                r.pending_confirm = out
            on_event(BridgeEvent("done", r))
        else:
            # "/opus ..." esplicito vince sempre; altrimenti un modello fisso scelto dall'utente batte il router
            explicit = text.strip().startswith("/")
            tier = route.tier if explicit else (self._preferred or route.tier)
            msg = route.text
            if self._outcome_note:
                msg = f"(esito della conferma precedente: {self._outcome_note})\n" + msg
                self._outcome_note = None
            self.session(tier, vision=Router.needs_vision(route.text)).send(msg, on_event)

    def shutdown(self) -> None:
        with self._lock:
            allv, self._sessions = list(self._sessions.values()), {}
        for s in allv:
            s.stop()
