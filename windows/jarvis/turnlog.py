"""Log dei token per turno (solo locale) e limite all'output degli strumenti letto dal modello."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from .core import Paths

_lock = threading.Lock()


def record(r, model: str, resolved_model: str | None, effort: str, vision: bool, session_turn: int, max_turns: int) -> None:
    """Una riga JSON per turno in turns.jsonl. Disattivabile con JARVIS_TURN_LOG=0."""
    if os.environ.get("JARVIS_TURN_LOG") == "0":
        return
    line = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"), "tier": r.tier.value, "model": model,
        "effort": effort, "vision": vision, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
        "cache_read_tokens": r.cache_read, "cache_write_tokens": r.cache_write, "cost_usd": r.cost_usd,
        "duration_ms": r.duration_ms, "session_turn": session_turn, "max_turns": max_turns, "is_error": r.is_error,
    }
    if resolved_model:
        line["resolved_model"] = resolved_model
    with _lock:
        try:
            with open(Paths.file("turns.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(line, sort_keys=True) + "\n")
        except OSError:
            pass


class OutputCap:
    DEFAULT_BYTES = 6 * 1024

    @staticmethod
    def limit() -> int:
        v = os.environ.get("JARVIS_TOOL_OUTPUT_MAX")
        try:
            n = int(v) if v is not None else None
        except ValueError:
            n = None
        return OutputCap.DEFAULT_BYTES if n is None or n < 0 else n

    @staticmethod
    def apply(s: str, limit: int | None = None) -> str:
        """Tiene l'inizio di `s` entro `limit` byte UTF-8 e aggiunge l'avviso di troncamento.
        Una richiesta di conferma in sospeso viene sempre conservata."""
        from .gate import MARKER
        limit = OutputCap.limit() if limit is None else limit
        raw = s.encode("utf-8")
        total = len(raw)
        if limit <= 0 or total <= limit:
            return s
        head = raw[:limit].decode("utf-8", errors="ignore")
        nl = head.rfind("\n")
        if nl >= 0 and len(head[:nl].encode("utf-8")) >= limit * 3 // 4:
            head = head[:nl]
        used = len(head.encode("utf-8"))
        out = (head + f"\n[OUTPUT TRONCATO: mostrati {used} di {total} byte, omessi {total - used}. "
               "Restringi la richiesta (meno elementi, --pages, filtri) se serve il resto.]")
        if MARKER not in head and MARKER in s:
            i = s.index(MARKER)
            out += "\n" + s[i:].split("\n", 1)[0]
        return out
