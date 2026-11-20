"""Calendario tramite Google Calendar API (equivalente di EventKit su macOS)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .. import gate
from ..core import ActionLog, Args, Refs, ToolError, When, start_of_day
from ..google_auth import call, service


def _iso(d: datetime) -> str:
    return d.astimezone().isoformat(timespec="seconds")


def _parse_g(s: dict) -> tuple[datetime, bool]:
    """Inizio/fine di un evento Google -> (datetime locale naive, tutto_il_giorno)."""
    if "dateTime" in s:
        return datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None), False
    return datetime.fromisoformat(s["date"]), True


def _range(spec: str) -> tuple[datetime, datetime, str]:
    today = start_of_day(datetime.now())
    s = spec.lower()
    if s in ("oggi", "today"):
        return today, today + timedelta(days=1), "oggi"
    if s in ("domani", "tomorrow"):
        d = today + timedelta(days=1)
        return d, d + timedelta(days=1), "domani"
    if s in ("settimana", "week", "7"):
        return today, today + timedelta(days=7), "nei prossimi 7 giorni"
    if s in ("mese", "month"):
        return today, today + timedelta(days=31), "nei prossimi 30 giorni"
    p = When.parse(spec)
    if not p:
        raise ToolError(f"periodo non valido: {spec}")
    d = start_of_day(p[0])
    return d, d + timedelta(days=1), When.fmt(d, time_=False)


def _calendars(svc, writable_only: bool = False) -> list[dict]:
    items = svc.calendarList().list(minAccessRole="writer" if writable_only else "freeBusyReader").execute().get("items", [])
    return [c for c in items if c.get("selected", True) or writable_only]


def _pick_calendar(svc, name: str | None) -> dict:
    cals = _calendars(svc, writable_only=True)
    if name:
        n = name.lower()
        hit = next((c for c in cals if c.get("summary", "").lower() == n), None) or \
            next((c for c in cals if n in c.get("summary", "").lower()), None)
        if hit:
            return hit
        raise ToolError(f'Calendario "{name}" non trovato. Disponibili: {", ".join(c.get("summary", "") for c in cals)}')
    primary = next((c for c in cals if c.get("primary")), None)
    if primary or cals:
        return primary or cals[0]
    raise ToolError("Nessun calendario scrivibile.")


def _find(svc, ref: str | None) -> tuple[str, dict]:
    v = Refs.resolve(ref) if ref else None
    if not v:
        raise ToolError("riferimento evento mancante: usa prima `cal list` e poi [eN]")
    parts = v.split("|")
    if len(parts) != 3:
        raise ToolError("riferimento non valido")
    cal_id, ev_id = parts[0], parts[1]
    return cal_id, svc.events().get(calendarId=cal_id, eventId=ev_id).execute()


def run(a: list[str], confirmed: bool = False, raw: list[str] | None = None) -> str:
    return call(lambda: _run(a, confirmed, raw or []))


def _run(a: list[str], confirmed: bool, raw: list[str]) -> str:
    sub = a[0] if a else "list"
    args = Args(a[1:], flags={"all"})
    svc = service("calendar", "v3")
    if sub in ("list", "oggi", "domani", "settimana"):
        spec = sub if sub != "list" else (" ".join(args.pos) or "oggi")
        start, end, label = _range(spec)
        evs: list[tuple[datetime, dict, str, str]] = []
        for cal in _calendars(svc):
            res = svc.events().list(calendarId=cal["id"], timeMin=_iso(start), timeMax=_iso(end), singleEvents=True,
                                    orderBy="startTime", maxResults=50).execute()
            for e in res.get("items", []):
                if e.get("status") == "cancelled":
                    continue
                evs.append((_parse_g(e["start"])[0], e, cal["id"], cal.get("summary", "")))
        evs.sort(key=lambda x: x[0])
        if not evs:
            return f"Nessun impegno {label}."
        refs = Refs.assign("e", [f"{cid}|{e['id']}|{st.timestamp()}" for st, e, cid, _ in evs])
        multi = (end - start).days > 1
        rows = []
        for ref, (st, e, _cid, cname) in list(zip(refs, evs))[:40]:
            en, all_day = _parse_g(e["end"])[0], "date" in e["start"]
            if all_day:
                when = (When.fmt(st, time_=False) + " tutto il giorno") if multi else "tutto il giorno"
            else:
                when = (When.fmt(st) if multi else When.hm(st)) + "-" + When.hm(en)
            s = f"[{ref}] {when} {e.get('summary', '(senza titolo)')}"
            if e.get("location"):
                s += f" @{e['location']}"
            rows.append(s + f" ({cname})")
        return f"{len(evs)} impegni {label}:\n" + "\n".join(rows)
    if sub in ("cals", "calendars"):
        return ", ".join(c.get("summary", "") + ("" if c.get("accessRole") in ("owner", "writer") else " (sola lettura)")
                         for c in _calendars(svc))
    if sub == "add":
        title = args.o("title", "titolo") or (" ".join(args.pos) if args.pos else None)
        if not title:
            raise ToolError("uso: cal add --title T --start DATA [--end DATA|--min 60]")
        s = args.o("start", "inizio")
        p = When.parse(s) if s else None
        if not p:
            raise ToolError('data di inizio mancante o non valida (es. --start "domani 15:00")')
        start, has_time = p
        cal = _pick_calendar(svc, args.o("cal", "calendar"))
        body: dict = {"summary": title}
        if not has_time and args.o("end") is None:
            body["start"] = {"date": start.date().isoformat()}
            body["end"] = {"date": (start + timedelta(days=1)).date().isoformat()}   # in Google la fine e' esclusiva
            all_day, end = True, start
        else:
            all_day = False
            e = args.o("end", "fine")
            ep = When.parse(e) if e else None
            if ep:
                end = ep[0] if ep[0] > start else start.replace(hour=ep[0].hour, minute=ep[0].minute)
            else:
                try:
                    mins = float(args.o("min", "minutes") or "60")
                except ValueError:
                    mins = 60
                end = start + timedelta(minutes=mins)
            body["start"] = {"dateTime": _iso(start)}
            body["end"] = {"dateTime": _iso(end)}
        if args.o("loc", "location", "luogo"):
            body["location"] = args.o("loc", "location", "luogo")
        if args.o("notes", "note"):
            body["description"] = args.o("notes", "note")
        al = args.o("alert", "avviso")
        if al:
            try:
                body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(float(al))}]}
            except ValueError:
                pass
        svc.events().insert(calendarId=cal["id"], body=body).execute()
        when = (When.fmt(start, time_=False) + " (tutto il giorno)") if all_day else f"{When.fmt(start)}-{When.hm(end)}"
        ActionLog.add("CALENDAR_SYNC", f'Creato evento "{title}" {when}')
        return f'Creato "{title}" {when} in {cal.get("summary", "")}.'
    if sub in ("move", "sposta"):
        cal_id, ev = _find(svc, args.pos[0] if args.pos else None)
        s = args.o("start", "inizio")
        p = When.parse(s) if s else None
        if not p:
            raise ToolError("uso: cal move <e1> --start DATA [--end DATA]")
        new_start = p[0]
        old_s, old_all = _parse_g(ev["start"])
        old_e = _parse_g(ev["end"])[0]
        dur = old_e - old_s
        e = args.o("end", "fine")
        ep = When.parse(e) if e else None
        new_end = ep[0] if ep else new_start + dur
        body = {"start": {"dateTime": _iso(new_start)}, "end": {"dateTime": _iso(new_end)}}
        svc.events().patch(calendarId=cal_id, eventId=ev["id"], body=body).execute()
        title = ev.get("summary", "")
        ActionLog.add("CALENDAR_SYNC", f'Spostato "{title}" a {When.fmt(new_start)}')
        return f'Spostato "{title}" a {When.fmt(new_start)}-{When.hm(new_end)}.'
    if sub in ("delete", "elimina"):
        cal_id, ev = _find(svc, args.pos[0] if args.pos else None)
        st = _parse_g(ev["start"])[0]
        desc = f'"{ev.get("summary", "")}" {When.fmt(st)}'
        if not confirmed:
            return gate.request(f"Eliminare l'evento {desc}", raw)
        svc.events().delete(calendarId=cal_id, eventId=ev["id"]).execute()
        ActionLog.add("CALENDAR_SYNC", f"Eliminato evento {desc}")
        return f"Eliminato {desc}."
    raise ToolError(f"sottocomando cal sconosciuto: {sub}")


def upcoming(minutes: int = 16) -> list[dict]:
    """Eventi che iniziano entro `minutes` (per gli avvisi proattivi). Solo eventi con orario."""
    svc = service("calendar", "v3")
    now = datetime.now()
    out = []
    for cal in _calendars(svc):
        res = svc.events().list(calendarId=cal["id"], timeMin=_iso(now), timeMax=_iso(now + timedelta(minutes=minutes)),
                                singleEvents=True, orderBy="startTime", maxResults=10).execute()
        for e in res.get("items", []):
            if e.get("status") == "cancelled" or "dateTime" not in e.get("start", {}):
                continue
            st = _parse_g(e["start"])[0]
            if st > now:
                out.append({"key": f"{cal['id']}|{e['id']}|{st.timestamp()}", "title": e.get("summary", ""),
                            "start": st, "location": e.get("location", "")})
    return out
