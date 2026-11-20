"""Conferma obbligatoria per le azioni critiche (invio mail, eliminazioni, cestino, spostamenti massivi).

Il modello puo' solo *richiedere* queste azioni: partono quando l'utente conferma dall'interfaccia
(`jarvis confirm`, che al modello e' vietato).
"""
from __future__ import annotations

import time

from .core import ActionLog, Store

FILE = "pending.json"
TTL = 3 * 60
MARKER = "IN ATTESA DI CONFERMA"


def _all() -> list[dict]:
    items = Store.load(FILE, []) or []
    return [p for p in items if time.time() - p.get("created", 0) < TTL]


def request(summary: str, argv: list[str]) -> str:
    items = _all()
    n = 1
    while any(p["id"] == f"p{n}" for p in items):
        n += 1
    p = {"id": f"p{n}", "summary": summary, "argv": argv, "created": time.time()}
    items.append(p)
    Store.save(FILE, items)
    ActionLog.add("CONFIRM", f"Richiesta conferma [{p['id']}]: {summary}")
    return f"{MARKER} [{p['id']}]: {summary}. Chiedi conferma all'utente; l'interfaccia esegue l'azione se conferma."


def list_pending() -> str:
    items = _all()
    if not items:
        return "Nessuna azione in attesa."
    return "\n".join(f"[{p['id']}] {p['summary']}" for p in items)


def latest_id() -> str | None:
    items = _all()
    return items[-1]["id"] if items else None


def latest_summary() -> str | None:
    """Riepilogo letto da pending.json (scritto solo dagli strumenti): e' cio' che mostra il dialogo,
    cosi' un testo dentro una mail o una pagina web non puo' falsificare cosa si sta confermando."""
    items = _all()
    return items[-1]["summary"] if items else None


def confirm(pid: str | None):
    from .cli import run  # import tardivo: cli importa gli strumenti che importano gate
    items = _all()
    target = pid or (items[-1]["id"] if items else None)
    idx = next((i for i, p in enumerate(items) if p["id"] == target), None)
    if idx is None:
        return "Nessuna azione in attesa da confermare.", 1
    p = items.pop(idx)
    Store.save(FILE, items)
    return run(p["argv"], confirmed=True)


def cancel_all() -> None:
    """Scarta ogni azione in attesa (ogni nuovo comando che non sia un si/no)."""
    items = _all()
    if not items:
        return
    Store.save(FILE, [])
    for p in items:
        ActionLog.add("CONFIRM", f"Scaduto senza conferma: {p['summary']}")


def cancel(pid: str | None) -> str:
    items = _all()
    if not items:
        return "Nessuna azione in attesa."
    target = pid or items[-1]["id"]
    idx = next((i for i, p in enumerate(items) if p["id"] == target), None)
    if idx is None:
        return f"Azione {target} non trovata."
    p = items.pop(idx)
    Store.save(FILE, items)
    ActionLog.add("CONFIRM", f"Annullato: {p['summary']}")
    return f"Annullato: {p['summary']}."
