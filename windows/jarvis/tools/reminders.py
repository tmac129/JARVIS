"""Promemoria tramite Google Tasks (equivalente dei Promemoria di macOS).

Limiti di Google Tasks: la scadenza e' solo una data (senza orario) e non esiste la priorita'.
JARVIS salva orario e priorita' nelle note del promemoria e le mostra nell'elenco.
"""
from __future__ import annotations

import re
from datetime import datetime

from ..core import ActionLog, Args, Refs, ToolError, When, fold
from ..google_auth import call, service

_PRIO_MARK = {"alta": "[priorità alta]", "media": "[priorità media]", "bassa": "[priorità bassa]"}


def _lists(svc) -> list[dict]:
    return svc.tasklists().list(maxResults=100).execute().get("items", [])


def _pick_list(svc, name: str | None) -> dict:
    lists = _lists(svc)
    if not lists:
        raise ToolError("Nessuna lista di promemoria su Google Tasks.")
    if name:
        n = name.lower()
        hit = next((x for x in lists if x["title"].lower() == n), None) or next((x for x in lists if n in x["title"].lower()), None)
        if hit:
            return hit
        raise ToolError(f'Lista "{name}" non trovata. Disponibili: {", ".join(x["title"] for x in lists)}')
    return lists[0]


def _due(t: dict) -> datetime | None:
    if not t.get("due"):
        return None
    d = datetime.fromisoformat(t["due"].replace("Z", "+00:00"))
    return datetime(d.year, d.month, d.day)   # Tasks conserva solo la data (a mezzanotte UTC)


def _time_in_notes(t: dict) -> str | None:
    m = re.search(r"\[ore (\d{2}:\d{2})\]", t.get("notes") or "")
    return m[1] if m else None


def _incomplete(svc, lists: list[dict]) -> list[tuple[dict, dict]]:
    out = []
    for lst in lists:
        res = svc.tasks().list(tasklist=lst["id"], showCompleted=False, showHidden=False, maxResults=100).execute()
        out += [(lst, t) for t in res.get("items", []) if t.get("status") != "completed" and t.get("title")]
    return out


def run(a: list[str], confirmed: bool = False, raw: list[str] | None = None) -> str:
    return call(lambda: _run(a))


def _run(a: list[str]) -> str:
    sub = a[0] if a else "list"
    args = Args(a[1:], flags={"all"})
    svc = service("tasks", "v1")
    if sub == "add":
        title = args.o("title", "titolo") or (" ".join(args.pos) if args.pos else None)
        if not title:
            raise ToolError("uso: rem add --title T [--due DATA] [--prio alta|media|bassa] [--list L]")
        lst = _pick_list(svc, args.o("list", "lista"))
        body: dict = {"title": title}
        notes: list[str] = []
        due_text = ""
        d = args.o("due", "quando", "scadenza")
        if d:
            p = When.parse(d, future_only=True)
            if not p:
                raise ToolError(f"data non valida: {d}")
            date, has_time = p
            body["due"] = date.strftime("%Y-%m-%dT00:00:00.000Z")
            if has_time:
                notes.append(f"[ore {date:%H:%M}]")
            due_text = " per " + When.fmt(date, time_=has_time)
        prio = (args.o("prio", "priority", "priorita") or "").lower()
        prio = {"high": "alta", "1": "alta", "medium": "media", "5": "media", "low": "bassa", "9": "bassa"}.get(prio, prio)
        if prio in _PRIO_MARK:
            notes.append(_PRIO_MARK[prio])
        if args.o("notes", "note"):
            notes.append(args.o("notes", "note"))
        if notes:
            body["notes"] = " ".join(notes)
        svc.tasks().insert(tasklist=lst["id"], body=body).execute()
        ActionLog.add("REMINDERS", f'Promemoria "{title}"{due_text}')
        return f'Promemoria "{title}"{due_text} aggiunto in {lst["title"]}.'
    if sub == "list":
        name = args.o("list", "lista")
        lists = [_pick_list(svc, name)] if name else _lists(svc)
        items = _incomplete(svc, lists)
        FAR = datetime(9999, 1, 1)
        items.sort(key=lambda x: (_due(x[1]) or FAR, x[1]["title"]))
        if not items:
            return "Nessun promemoria da completare."
        shown = items[:100 if args.has("all") else 25]
        refs = Refs.assign("r", [f"{l['id']}|{t['id']}" for l, t in shown])
        rows = []
        for ref, (l, t) in zip(refs, shown):
            s = f"[{ref}] {t['title']}"
            due = _due(t)
            if due:
                hm = _time_in_notes(t)
                s += f" ({When.fmt(due, time_=False)}{' ' + hm if hm else ''})"
            if _PRIO_MARK["alta"] in (t.get("notes") or ""):
                s += " !"
            rows.append(s + " {" + l["title"] + "}")
        return f"{len(items)} da fare:\n" + "\n".join(rows)
    if sub == "lists":
        return ", ".join(x["title"] for x in _lists(svc))
    if sub in ("done", "fatto"):
        q = " ".join(args.pos)
        if not q:
            raise ToolError("uso: rem done <r1|testo>")
        ref = Refs.resolve(q)
        if ref and "|" in ref:
            list_id, task_id = ref.split("|", 1)
            t = svc.tasks().get(tasklist=list_id, task=task_id).execute()
        else:
            matches = [(l, t) for l, t in _incomplete(svc, _lists(svc)) if fold(q) in fold(t["title"])]
            if len(matches) != 1:
                raise ToolError(f'nessun promemoria contiene "{q}"' if not matches else
                                "più promemoria corrispondono: " + "; ".join(t["title"] for _, t in matches[:5]) +
                                ". Usa `rem list` e [rN].")
            list_id, t = matches[0][0]["id"], matches[0][1]
        svc.tasks().patch(tasklist=list_id, task=t["id"], body={"status": "completed"}).execute()
        ActionLog.add("REMINDERS", f'Completato "{t["title"]}"')
        return f'Completato "{t["title"]}".'
    raise ToolError(f"sottocomando rem sconosciuto: {sub}")
