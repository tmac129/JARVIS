"""Sveglie (Utilita' di pianificazione di Windows) e timer (processi in background).

Le sveglie sopravvivono alla chiusura dell'app e al riavvio: sono attivita' pianificate `JARVIS\\alarm_aN`
create da un file XML (formato data indipendente dalla lingua di Windows).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from ..core import IS_WINDOWS, ActionLog, Args, Paths, Store, ToolError, When, run_process, spawn_detached

TASK_FOLDER = "JARVIS"


def _task_name(alarm_id: str) -> str:
    return f"{TASK_FOLDER}\\alarm_{alarm_id}"


def _task_xml(date: datetime, daily: bool, alarm_id: str) -> str:
    cmd = Paths.command()
    trigger_body = f"<StartBoundary>{date:%Y-%m-%dT%H:%M:%S}</StartBoundary><Enabled>true</Enabled>"
    trigger = (f"<CalendarTrigger>{trigger_body}<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
               if daily else f"<TimeTrigger>{trigger_body}</TimeTrigger>")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>J.A.R.V.I.S. sveglia {alarm_id}</Description></RegistrationInfo>
  <Triggers>{trigger}</Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(cmd[0])}</Command><Arguments>{escape(' '.join(cmd[1:]) + ' alarm _fire ' + alarm_id)}</Arguments></Exec></Actions>
</Task>
"""


def install(alarm_id: str, date: datetime, daily: bool) -> None:
    if not IS_WINDOWS:
        raise ToolError("le sveglie richiedono Windows (Utilità di pianificazione)")
    fd, path = tempfile.mkstemp(suffix=".xml", prefix="jarvis_alarm_")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:     # codifica UTF-16 con BOM, come richiede schtasks
            f.write(_task_xml(date, daily, alarm_id))
        r = run_process(["schtasks.exe", "/Create", "/TN", _task_name(alarm_id), "/XML", path, "/F"], timeout=30)
        if r.code != 0:
            raise ToolError(f"Utilità di pianificazione: {r.err or r.out}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def remove(alarm_id: str) -> None:
    if IS_WINDOWS:
        try:
            run_process(["schtasks.exe", "/Delete", "/TN", _task_name(alarm_id), "/F"], timeout=30)
        except ToolError:
            pass


def run_alarm(a: list[str], confirmed: bool = False, raw: list[str] | None = None) -> str:
    sub = a[0] if a else "list"
    args = Args(a[1:], flags={"daily", "ognigiorno"})
    alarms: list[dict] = Store.load("alarms.json", []) or []
    if sub in ("set", "add"):
        spec = " ".join(([args.o("date", "data")] if args.o("date", "data") else []) + args.pos)
        p = When.parse(spec, future_only=True)
        if not p or not p[1]:
            raise ToolError("orario non valido: usa alarm set HH:MM [--date DATA]")
        date = p[0]
        daily = args.has("daily") or args.has("ognigiorno")
        label = args.o("label", "etichetta") or "Sveglia"
        n = 1
        while any(x["id"] == f"a{n}" for x in alarms):
            n += 1
        al = {"id": f"a{n}", "date": date.isoformat(), "label": label, "daily": daily}
        install(al["id"], date, daily)
        alarms.append(al)
        Store.save("alarms.json", alarms)
        when = f"ogni giorno alle {When.hm(date)}" if daily else When.fmt(date)
        ActionLog.add("CLOCK", f"Sveglia {when} ({label})")
        return f"Sveglia [{al['id']}] impostata {when}."
    if sub == "list":
        limit = datetime.now() - timedelta(seconds=120)
        alarms = [x for x in alarms if x["daily"] or datetime.fromisoformat(x["date"]) > limit]
        if not alarms:
            return "Nessuna sveglia attiva."
        return "\n".join(
            f"[{x['id']}] " + (("ogni giorno " + When.hm(datetime.fromisoformat(x['date']))) if x["daily"]
                               else When.fmt(datetime.fromisoformat(x["date"]))) + f" {x['label']}" for x in alarms)
    if sub in ("cancel", "delete", "off"):
        aid = args.pos[0].strip("[]") if args.pos else None
        al = next((x for x in alarms if x["id"] == aid), None)
        if not al:
            raise ToolError("sveglia non trovata: usa alarm list")
        remove(al["id"])
        alarms = [x for x in alarms if x["id"] != aid]
        Store.save("alarms.json", alarms)
        t = When.hm(datetime.fromisoformat(al["date"]))
        ActionLog.add("CLOCK", f"Sveglia {t} annullata")
        return f"Sveglia delle {t} annullata."
    if sub == "_fire":
        aid = args.pos[0] if args.pos else None
        if not aid:
            return ""
        al = next((x for x in alarms if x["id"] == aid), None)
        label = al["label"] if al else "Sveglia"
        extra = "" if label == "Sveglia" else label
        ring("Sveglia", label, f"Signore, sono le {When.hm(datetime.now())}. {extra}".strip())
        if al and not al["daily"]:
            Store.save("alarms.json", [x for x in alarms if x["id"] != aid])
            remove(aid)
        return ""
    raise ToolError(f"sottocomando alarm sconosciuto: {sub}")


# ----------------------------------------------------------------------------- timer

def _alive(pid: int) -> bool:
    import psutil
    return psutil.pid_exists(pid)


def run_timer(a: list[str]) -> str:
    now = datetime.now()
    timers = [t for t in (Store.load("timers.json", []) or [])
              if datetime.fromisoformat(t["end"]) > now and _alive(t["pid"])]
    args = Args(a)
    first = args.pos[0] if args.pos else "list"
    if first in ("list", "timers"):
        Store.save("timers.json", timers)
        if not timers:
            return "Nessun timer attivo."
        return "\n".join(f"[{t['id']}] {t['label']}: mancano "
                         f"{When.duration_text((datetime.fromisoformat(t['end']) - now).total_seconds())}" for t in timers)
    if first in ("cancel", "stop", "off"):
        tid = args.pos[1].strip("[]") if len(args.pos) > 1 else (timers[-1]["id"] if timers else None)
        t = next((x for x in timers if x["id"] == tid), None)
        if not t:
            raise ToolError("nessun timer da annullare")
        import psutil
        try:
            psutil.Process(t["pid"]).terminate()
        except psutil.Error:
            pass
        Store.save("timers.json", [x for x in timers if x["id"] != tid])
        ActionLog.add("CLOCK", f"Timer {t['label']} annullato")
        return f"Timer {t['label']} annullato."
    if first == "_wait":
        if len(args.pos) < 2:
            return ""
        import time
        try:
            secs = float(args.pos[1])
        except ValueError:
            return ""
        label = " ".join(args.pos[2:])
        time.sleep(secs)
        ring("Timer", label or "Tempo scaduto", f"Signore, il timer {label + ' ' if label else ''}è scaduto.")
        return ""
    secs = When.duration(" ".join(args.pos))
    if secs is None:
        raise ToolError("durata non valida: usa timer 20m | 90s | 1h30m")
    if secs != secs or secs == float("inf") or secs > 7 * 86400:
        raise ToolError("durata troppo lunga: massimo 7 giorni")
    label = args.o("label", "etichetta") or When.duration_text(secs)
    n = 1
    while any(x["id"] == f"t{n}" for x in timers):
        n += 1
    pid = spawn_detached(Paths.command() + ["timer", "_wait", str(int(secs)), label])
    end = now + timedelta(seconds=secs)
    timers.append({"id": f"t{n}", "end": end.isoformat(), "label": label, "pid": pid})
    Store.save("timers.json", timers)
    ActionLog.add("CLOCK", f"Timer {When.duration_text(secs)} avviato")
    return f"Timer [t{n}] di {When.duration_text(secs)} avviato, scade alle {When.hm(end)}."


# ----------------------------------------------------------------------------- suoneria

_TOAST = ("$t=[Windows.UI.Notifications.ToastTemplateType,Windows.UI.Notifications,ContentType=WindowsRuntime]::ToastText02;"
          "$x=[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]::GetTemplateContent($t);"
          "$n=$x.GetElementsByTagName('text');"
          "$n.Item(0).AppendChild($x.CreateTextNode($env:JARVIS_TOAST_TITLE))|Out-Null;"
          "$n.Item(1).AppendChild($x.CreateTextNode($env:JARVIS_TOAST_BODY))|Out-Null;"
          "$toast=[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime]::new($x);"
          "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]"
          "::CreateToastNotifier('J.A.R.V.I.S.').Show($toast)")


def toast(title: str, body: str) -> None:
    """Notifica di Windows. Titolo e testo viaggiano nell'ambiente, mai dentro lo script."""
    if not IS_WINDOWS:
        return
    import subprocess
    env = dict(os.environ, JARVIS_TOAST_TITLE=f"J.A.R.V.I.S. {title}", JARVIS_TOAST_BODY=body)
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _TOAST],
                       env=env, timeout=15, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass


def ring(title: str, message: str, speech: str) -> None:
    """Suono + notifica + voce."""
    from .. import speech as sp
    ActionLog.add("CLOCK", f"{title}: {message}")
    toast(title, message)
    sp.beep(3)
    sp.say_blocking(speech)
