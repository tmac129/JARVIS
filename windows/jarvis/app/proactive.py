"""J.A.R.V.I.S. che parla per primo: briefing del mattino, impegni tra 15 minuti, batteria scarica.
Un controllo al minuto, poche query locali, nessun token finche' non parte il briefing."""
from __future__ import annotations

import threading
from datetime import datetime

import psutil

from ..core import Store
from ..modules import Module, Modules


class Proactive:
    def __init__(self, prefs, on_alert, on_briefing, notify):
        self.prefs = prefs
        self.on_alert = on_alert        # (module, text)
        self.on_briefing = on_briefing
        self.notify = notify            # (title, body)
        self._alerted: set[str] = set()
        self._batt_warned = 100
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(8):
            return
        while not self._stop.is_set():
            try:
                self.check()
            except Exception:
                pass
            self._stop.wait(60)

    def check(self) -> None:
        if self.prefs.get("proMeetings", True) and Modules.is_enabled(Module.calendar):
            self._check_meetings()
        if self.prefs.get("proBattery", True):
            self._check_battery()
        if self.prefs.get("proBriefing", True):
            self._check_briefing()

    def _check_meetings(self) -> None:
        if not Store.load("google_token.json"):
            return
        from ..tools.calendar import upcoming
        try:
            events = upcoming(16)
        except Exception:
            return          # rete assente o account scaduto: niente avvisi, nessun errore a schermo
        now = datetime.now()
        for e in events:
            if e["key"] in self._alerted:
                continue
            self._alerted.add(e["key"])
            mins = max(1, int((e["start"] - now).total_seconds() // 60))
            text = f"Signore, tra {mins} minuti: {e['title'] or 'un impegno'}"
            if e["location"]:
                text += f", {e['location']}"
            self.notify(f"Impegno tra {mins} minuti", e["title"])
            self.on_alert("CALENDAR_SYNC", text + ".")

    def _check_battery(self) -> None:
        b = psutil.sensors_battery()
        if b is None:
            return
        if b.power_plugged:
            self._batt_warned = 100
            return
        pct = round(b.percent)
        for threshold in (20, 10, 5):
            if pct <= threshold and self._batt_warned > threshold:
                self._batt_warned = threshold
                self.notify(f"Batteria al {pct}%", "Collega l'alimentatore.")
                self.on_alert("POWER", f"Signore, la batteria è al {pct} per cento. Le consiglio di collegare l'alimentatore.")
                break

    def _check_briefing(self) -> None:
        h = datetime.now().hour
        if h < self.prefs.get("proBriefingHour", 7) or h >= 12:
            return
        today = datetime.now().date().isoformat()
        if self.prefs.get("proBriefingDone") == today:
            return
        self.prefs.set("proBriefingDone", today)
        self.on_briefing()
