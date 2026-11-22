"""Punto d'ingresso unico di ogni strumento. Usato dal comando `jarvis` (chiamato da Claude via Bash)
e in-process dal router e dall'app."""
from __future__ import annotations

import importlib
import os
import sys

from . import gate
from .core import ToolError
from .modules import Module, Modules

USAGE = """\
jarvis mail unread [N] | search <testo> [N] | read <m1> | draft|send --to a@b[,c] --subject S --body B [--attach PATH|f1]
jarvis contact <nome>
jarvis cal list [oggi|domani|settimana|DATA] | add --title T --start DATA [--end DATA|--min 60] [--loc L] [--notes N] [--cal NOME] | move <e1> --start DATA | delete <e1> | cals
jarvis rem add --title T [--due DATA] [--prio alta|media|bassa] [--list L] | list [--list L] | done <r1|testo> | lists
jarvis alarm set HH:MM [--date DATA] [--label L] [--daily] | list | cancel <a1>
jarvis timer <20m|90s|1h30m> [--label L] | timer list | timer cancel [t1]
jarvis file find <nome> [--ext pdf] [--in DIR] [--days N] [--dirs] | ls DIR [--ext pdf] | move|copy <SRC...> --to DIR | rename <SRC> <NOME> | mkdir DIR | open|reveal <SRC> | trash <SRC...>
jarvis wa send --to <nome|numero> --text T   (WhatsApp)
jarvis sys open|quit <app> | apps | volume <0-100|su|giu|muto|attiva> | brightness <0-100|su|giu> | wifi on|off | dark on|off | lock | sleep | screenshot | battery
jarvis music play [brano|artista] | pause | next | prev | now   (qualsiasi player)
jarvis note add --title T [--body B] [--folder F] | list | search <testo> | read <nt1> | append <nt1> --text T
jarvis doc read <f1|percorso> [--pages 1-5]          (PDF, Word, RTF, testo, immagini)
jarvis screen [--full]                               (cattura la finestra che l'utente sta guardando)
jarvis now
jarvis pending | confirm [p1] | cancel [p1]      (solo interfaccia utente)
jarvis reset                                     (solo interfaccia utente, da terminale: elimina tutti i dati locali)
jarvis ask "<testo>" | chat                      (test del bridge Claude)
"""

# comando -> (modulo, funzione). Import tardivo: un modulo che manca non rompe gli altri comandi.
_TOOLS = {
    "mail": ("mail", "run_mail"), "contact": ("mail", "run_contact"), "contatto": ("mail", "run_contact"),
    "cal": ("calendar", "run"), "calendar": ("calendar", "run"),
    "rem": ("reminders", "run"), "reminder": ("reminders", "run"), "reminders": ("reminders", "run"),
    "alarm": ("alarm", "run_alarm"), "sveglia": ("alarm", "run_alarm"),
    "timer": ("alarm", "run_timer"), "timers": ("alarm", "run_timer"),
    "file": ("files", "run"), "files": ("files", "run"),
    "wa": ("whatsapp", "run"), "whatsapp": ("whatsapp", "run"),
    "sys": ("system", "run"), "system": ("system", "run"),
    "music": ("music", "run"), "musica": ("music", "run"),
    "note": ("notes", "run"), "notes": ("notes", "run"),
    "doc": ("docs", "run"), "docs": ("docs", "run"),
    "screen": ("screen", "run"), "schermo": ("screen", "run"),
    "google": ("google_cmd", "run"),
}
_NEEDS_GATE = {"mail", "cal", "calendar", "rem", "reminder", "reminders", "alarm", "sveglia", "file", "files", "wa", "whatsapp", "sys", "system"}


def run(argv: list[str], confirmed: bool = False) -> tuple[str, int]:
    if not argv:
        return USAGE, 0
    cmd, rest = argv[0], argv[1:]
    m = Module.for_command(cmd)
    if m is not None and not Modules.is_enabled(m):
        return f"ERRORE: {Modules.disabled_message(m)}", 1
    try:
        if cmd in _TOOLS:
            modname, fn = _TOOLS[cmd]
            mod = importlib.import_module(f"{__package__}.tools.{modname}")
            f = getattr(mod, fn)
            if cmd in _NEEDS_GATE:
                out = f(rest, confirmed=confirmed, raw=argv)
            elif cmd in ("timer", "timers"):
                out = f(["list"] if cmd == "timers" else rest)
            else:
                out = f(rest)
        elif cmd in ("now", "ora"):
            from .core import When
            from datetime import datetime
            out = When.fmt(datetime.now())
        elif cmd == "pending":
            out = gate.list_pending()
        elif cmd == "confirm":
            return gate.confirm(rest[0] if rest else None)
        elif cmd == "cancel":
            out = gate.cancel(rest[0] if rest else None)
        elif cmd == "_account":
            from .bridge import ClaudeSession
            installed, logged, plan = ClaudeSession.account_status()
            out = ("Claude Code non installato" if not installed else
                   f"Account Claude: {plan or 'collegato'}" if logged else "Account Claude: non collegato")
        elif cmd in ("help", "-h", "--help"):
            out = USAGE
        else:
            raise ToolError(f"comando sconosciuto: {cmd}\n{USAGE}")
        return out, 0
    except ToolError as e:
        return f"ERRORE: {e}", 1
    except Exception as e:  # un errore imprevisto di una libreria non deve mai far cadere il bridge
        return f"ERRORE: {type(e).__name__}: {e}", 1


def _print_turn(r) -> None:
    if r.local:
        print(f"JARVIS [LOCALE, 0 token]: {r.text}")
    else:
        print(f"JARVIS [{r.tier.value}]: {r.text}")
        ctx = r.input_tokens + r.cache_read + r.cache_write
        print(f"   {r.duration_ms / 1000:.1f}s | contesto {ctx} tok (cache letta {r.cache_read}, scritta {r.cache_write})"
              f" | output {r.output_tokens} tok | ${r.cost_usd:.5f}")
    if r.pending_confirm:
        print('   >> Azione critica in attesa: rispondi "sì" per confermare o "no" per annullare.')


def _converse(brain, text: str) -> None:
    import threading
    done = threading.Event()

    def on_event(ev):
        if ev.kind == "thinking":
            print(f"   ... {ev.value.label}")
        elif ev.kind == "tool":
            print(f"   $ {ev.value}")
        elif ev.kind == "toolResult" and os.environ.get("JARVIS_DEBUG"):
            print("\n".join("     | " + ln for ln in ev.value.splitlines()))
        elif ev.kind == "done":
            _print_turn(ev.value)
            done.set()

    brain.handle(text, on_event)
    done.wait()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # Difesa in profondita': quando e' il modello a eseguire `jarvis` (JARVIS_AGENT) non puo' mai confermare
    # le proprie azioni critiche, nemmeno se un comando sfuggisse ai filtri --disallowedTools di Claude Code.
    if os.environ.get("JARVIS_AGENT") and argv and argv[0] in ("confirm", "cancel", "reset"):
        print("ERRORE: le conferme arrivano solo dall'interfaccia utente.")
        return 1
    first = argv[0] if argv else ""
    if first == "ask":
        from .bridge import JarvisBrain
        brain = JarvisBrain()
        _converse(brain, " ".join(argv[1:]))
        brain.shutdown()
        return 0
    if first == "chat":
        from .bridge import JarvisBrain
        brain = JarvisBrain()
        brain.prewarm()
        print("J.A.R.V.I.S. online. Scrivi un comando (vuoto per uscire). /sonnet, /opus o /fable per forzare il modello.")
        while True:
            try:
                line = input("> ")
            except EOFError:
                break
            if not line.strip():
                break
            _converse(brain, line)
        brain.shutdown()
        return 0
    if first == "route":
        from .router import Router
        print(Router.route(" ".join(argv[1:])))
        return 0
    if first == "hud":
        from .app.hud import main as hud_main
        return hud_main()
    if first == "reset":
        from .reset import interactive
        return interactive()
    if first == "doctor":
        from .doctor import run_doctor
        return run_doctor()
    if first == "setup-voice":
        from .app.voice import setup_model
        return setup_model()
    out, code = run(argv)
    if os.environ.get("JARVIS_AGENT"):
        from .turnlog import OutputCap
        out = OutputCap.apply(out)
    if out:
        print(out)
    return code


def hud_entry() -> int:
    """Voce `jarvis-hud` (applicazione grafica, senza console)."""
    from .app.hud import main as hud_main
    return hud_main()
