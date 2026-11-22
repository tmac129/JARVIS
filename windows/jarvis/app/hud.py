"""Applicazione J.A.R.V.I.S. per Windows: finestra HUD (pywebview), icona nella barra delle applicazioni,
scorciatoie globali, voce, telemetria, avvisi proattivi e server per il telefono.

Equivalente di AppDelegate.swift. Il HUD e' la stessa interfaccia HTML della versione macOS.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from .. import gate, permissions, prompt
from ..bridge import BridgeEvent, JarvisBrain, TurnResult
from ..core import IS_WINDOWS, ActionLog, Paths, Store
from ..modules import Module, Modules
from ..router import Tier
from .proactive import Proactive
from .remote import RemoteServer, local_addresses, qr_png
from .telemetry import Telemetry
from .voice import Listener, SpeechThread, find_model

HUD_DIR = Path(__file__).resolve().parent.parent / "HUD"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

MODULE_BY_COMMAND = [
    ("jarvis mail", "MAIL_PROTOCOL"), ("jarvis cal", "CALENDAR_SYNC"), ("jarvis rem", "REMINDERS"),
    ("jarvis alarm", "CLOCK"), ("jarvis timer", "CLOCK"), ("jarvis file", "FILE_SYSTEM"), ("jarvis contact", "CONTACTS"),
    ("jarvis wa", "WHATSAPP"), ("jarvis sys", "SYSTEM"), ("jarvis music", "MUSIC"), ("jarvis note", "NOTES"),
    ("jarvis doc", "DOCUMENTS"), ("jarvis screen", "VISION"),
]


def module_for(cmd: str) -> str:
    c = cmd.lower()
    for key, mod in MODULE_BY_COMMAND:
        if key in c:
            return mod
    if "view" in c and ("/" in c or "\\" in c):
        return "VISION"
    return "NEURAL_LINK"


class Prefs:
    """Preferenze dell'app in prefs.json (equivalente di UserDefaults)."""

    def __init__(self):
        self._lock = threading.Lock()

    def get(self, key: str, default=None):
        return (Store.load("prefs.json", {}) or {}).get(key, default)

    def set(self, key: str, value) -> None:
        with self._lock:
            d = Store.load("prefs.json", {}) or {}
            if value is None:
                d.pop(key, None)
            else:
                d[key] = value
            Store.save("prefs.json", d)


class Api:
    """Unico oggetto esposto al JavaScript del HUD (window.pywebview.api.post). I metodi con _ non sono esposti."""

    def __init__(self, app: "App"):
        self._app = app

    def post(self, payload: str) -> None:
        try:
            self._app.on_message(json.loads(payload))
        except Exception as e:  # un messaggio malformato non deve far cadere l'app
            ActionLog.add("SYS", f"Messaggio HUD non valido: {type(e).__name__}")


class App:
    def __init__(self):
        self.prefs = Prefs()
        self.brain = JarvisBrain()
        self.telemetry = Telemetry()
        self.window = None
        self.icon = None
        self.hud_ready = False
        self.visible = True
        self.busy = False
        self.feed_offset = 0
        self.turns = 0
        self.cost = 0.0
        self.last_context = 0
        self.last_turn: TurnResult | None = None
        self.last_started = time.time()
        self.speak_reply = True
        self.reply_handler = None
        self.claude_account: tuple[bool, bool, str | None] | None = None
        self.claude_account_at = 0.0
        self._send_lock = threading.Lock()
        self._work = threading.Lock()
        self._tick_stop = threading.Event()
        self._tick_thread: threading.Thread | None = None
        self.speech = SpeechThread(on_speaking=self._on_speaking, on_level=lambda v: self.send({"type": "level", "value": v}))
        self.listener = Listener(
            self.speech, on_level=lambda v: self.send({"type": "level", "value": v}),
            on_partial=lambda t: self.send({"type": "user", "text": t}), on_command=self._on_voice_command,
            on_listening=self._on_listening, on_wake=self.show, on_error=self._on_voice_error)
        self.proactive = Proactive(self.prefs, self._on_alert, lambda: self.briefing_now(), self.notify)
        self.remote = RemoteServer(self._mobile_page, self._remote_handler)

    # ------------------------------------------------------------------ avvio

    def run(self) -> int:
        import webview
        self.brain.preferred_tier = Tier(self.prefs.get("tier")) if self.prefs.get("tier") in [t.value for t in Tier] else None
        self.brain.effort = self.prefs.get("effort")
        self.speech.set_voice(self.prefs.get("voiceID"))
        self.window = webview.create_window(
            "J.A.R.V.I.S.", url=str(HUD_DIR / "index.html"), js_api=Api(self), width=1180, height=740,
            min_size=(980, 620), background_color="#05090f", on_top=bool(self.prefs.get("alwaysOnTop", False)))
        self.window.events.closing += self._on_closing
        self.window.events.minimized += lambda: self._set_visible(False)
        self.window.events.restored += lambda: self._set_visible(True)
        webview.start(self._after_start, private_mode=False, storage_path=str(Paths.support / "webview"))
        return 0

    def _after_start(self) -> None:
        """Parte quando la finestra e' pronta (thread separato dal ciclo grafico)."""
        self._build_tray()
        self._register_hotkeys()
        self.proactive.start()
        threading.Thread(target=self._track_foreground, daemon=True).start()
        if self.prefs.get("hotword"):
            self.listener.set_hotword(True)
        if self.prefs.get("remote"):
            try:
                self.remote.start()
            except OSError:
                pass
        self.refresh_claude_account()
        self.brain.prewarm()
        self._start_tick()

    # ------------------------------------------------------------------ finestra

    def _on_closing(self):
        """La X nasconde la finestra (l'app resta nella barra); si esce dal menu."""
        if getattr(self, "_quitting", False):
            return True
        self.hide()
        return False

    def _set_visible(self, v: bool) -> None:
        self.visible = v
        self.send({"type": "visible", "value": v})
        if v:
            self._start_tick()

    def show(self) -> None:
        if not self.window:
            return
        try:
            self.window.restore()
            self.window.show()
        except Exception:
            pass
        self._set_visible(True)

    def hide(self) -> None:
        self.send({"type": "visible", "value": False})
        self.visible = False
        try:
            self.window.hide()
        except Exception:
            pass

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    # ------------------------------------------------------------------ ponte JS

    def send(self, msg: dict) -> None:
        if not self.window or not (self.hud_ready or msg.get("type") == "visible"):
            return
        js = f"window.HUD && HUD.recv({json.dumps(msg, ensure_ascii=False)})"
        try:
            with self._send_lock:
                self.window.evaluate_js(js)
        except Exception:
            pass

    def on_message(self, m: dict) -> None:
        t = m.get("type")
        if t == "ready":
            self.hud_ready = True
            self.send({"type": "model", "label": self.model_label()})
            self.send({"type": "native"})
            self.poll_feed(initial=True)
            self.tick()
            self.send({"type": "visible", "value": self.visible})
        elif t == "command" and isinstance(m.get("text"), str):
            self.command(m["text"])
        elif t == "confirm":
            self.resolve_pending(True)
        elif t == "cancel":
            self.resolve_pending(False)
        elif t == "hide":
            self.speech.stop()
            self.listener.cancel_listening() if self.listener.capturing else self.hide()
        elif t == "mic":
            self.toggle_mic()
        elif t == "stopSpeech":
            self.speech.stop()

    def model_label(self, tier: Tier | None = None) -> str:
        tier = tier or self.brain.default_tier
        mode = "AUTO" if self.brain.preferred_tier is None else "FISSO"
        return f"{tier.label} // {mode} // EFFORT {(self.brain.effort or tier.effort).upper()}"

    # ------------------------------------------------------------------ telemetria e feed

    def _start_tick(self) -> None:
        if self._tick_thread and self._tick_thread.is_alive():
            return
        self._tick_stop.clear()
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def _tick_loop(self) -> None:
        while not self._tick_stop.is_set() and self.visible:
            self.tick()
            time.sleep(1)

    def tick(self) -> None:
        if not self.hud_ready:
            return
        self.send(self.telemetry.sample())
        self.poll_feed()

    def poll_feed(self, initial: bool = False) -> None:
        path = Paths.file("actions.log")
        try:
            size = path.stat().st_size
        except OSError:
            return
        if initial:
            with open(path, "rb") as f:
                f.seek(max(0, size - 4000))
                lines = f.read().decode("utf-8", errors="replace").splitlines()[-12:]
            for ln in lines:
                o = self._parse_feed(ln)
                if o:
                    o["fresh"] = False
                    self.send(o)
            self.feed_offset = size
            return
        if size < self.feed_offset:   # log ruotato o azzerato: rileggi dall'inizio
            self.feed_offset = 0
        if size == self.feed_offset:
            return
        with open(path, "rb") as f:
            f.seek(self.feed_offset)
            data = f.read()
        self.feed_offset = size
        for ln in data.decode("utf-8", errors="replace").splitlines():
            o = self._parse_feed(ln)
            if o:
                self.send(o)

    @staticmethod
    def _parse_feed(line: str) -> dict | None:
        try:
            o = json.loads(line)
        except ValueError:
            return None
        if not isinstance(o, dict):
            return None
        o["type"] = "feed"
        return o

    # ------------------------------------------------------------------ comandi

    def command(self, text: str, speak: bool | None = None, completion=None) -> None:
        if self.busy:
            msg = "Un momento, signore: sto ancora elaborando."
            if completion:
                completion(msg)
            else:
                self.send({"type": "reply", "text": msg})
            return
        self.speech.stop()
        self.busy = True
        self.reply_handler = completion
        self.speak_reply = self.voice_replies if speak is None else speak
        self.send({"type": "state", "state": "thinking", "module": "NEURAL_LINK"})
        started = time.time()
        threading.Thread(target=lambda: self.brain.handle(text, lambda ev: self._on_event(ev, started)),
                         daemon=True).start()

    def _on_event(self, ev: BridgeEvent, started: float) -> None:
        if ev.kind == "thinking":
            self.send({"type": "model", "label": self.model_label(ev.value)})
        elif ev.kind == "tool":
            self.send({"type": "state", "state": "thinking", "module": module_for(ev.value)})
            self.send({"type": "tool", "text": ev.value})
        elif ev.kind == "confirmNeeded":
            s = gate.latest_summary()
            if s:
                self.send({"type": "confirm", "text": s})
        elif ev.kind == "done":
            r: TurnResult = ev.value
            self.busy = False
            self.last_turn, self.last_started = r, started
            self.send({"type": "reply", "text": r.text})
            h, self.reply_handler = self.reply_handler, None
            if h:
                h(r.text)
            if not r.local:
                self.turns += 1
                self.cost += r.cost_usd
                self.last_context = r.input_tokens + r.cache_read + r.cache_write
            self.send_stats(f"{time.time() - started:.1f} s" + (" (locale)" if r.local else ""))
            self._menu_changed()
            summary = gate.latest_summary()
            if r.pending_confirm and summary:
                self.send({"type": "confirm", "text": summary})
            else:
                self.send({"type": "confirmClear"})
                self.send({"type": "state", "state": "standby"})
            if self.speak_reply:
                self.speech.speak(r.text)
            self.poll_feed()

    def send_stats(self, latency: str) -> None:
        self.send({"type": "stats", "turns": self.turns, "context": self.last_context, "cost": self.cost, "latency": latency})

    def resolve_pending(self, confirm: bool) -> None:
        self.send({"type": "confirmClear"})
        self.send({"type": "state", "state": "thinking", "module": "CONFIRM"})

        def work():
            out, _code = gate.confirm(None) if confirm else (gate.cancel(None), 0)
            self.brain.note_outcome(out)
            self.send({"type": "reply", "text": out})
            if self.voice_replies:
                self.speech.speak(out)
            self.send({"type": "state", "state": "standby"})
            self.poll_feed()

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ voce

    @property
    def voice_replies(self) -> bool:
        return bool(self.prefs.get("voiceReplies", True))

    def _on_speaking(self, on: bool) -> None:
        if self.busy or self.listener.capturing:
            return
        self.send({"type": "state", "state": "speaking" if on else "standby"})

    def _on_listening(self, on: bool) -> None:
        self.send({"type": "mic", "on": on})
        if on:
            self.send({"type": "state", "state": "listening", "module": "AUDIO_INPUT"})
        elif not self.busy:
            self.send({"type": "state", "state": "standby"})

    def _on_voice_command(self, text: str) -> None:
        self.send({"type": "user", "text": text})
        self.command(text, speak=True)

    def _on_voice_error(self, text: str) -> None:
        self.send({"type": "reply", "text": text})
        self.send({"type": "mic", "on": False})

    def toggle_mic(self) -> None:
        threading.Thread(target=(self.listener.cancel_listening if self.listener.capturing else self.listener.listen_once),
                         daemon=True).start()

    # ------------------------------------------------------------------ iniziativa

    def notify(self, title: str, body: str) -> None:
        if self.icon:
            try:
                self.icon.notify(body or title, "J.A.R.V.I.S. · " + title)
            except Exception:
                pass

    def _on_alert(self, module: str, text: str) -> None:
        ActionLog.add(module, text)
        self.send({"type": "reply", "text": text})
        if self.voice_replies and not self.busy:
            self.speech.speak(text)
        self.poll_feed()

    def briefing_now(self) -> None:
        self.show()
        self.send({"type": "user", "text": "Briefing"})
        self.command(prompt.briefing(), speak=True)

    # ------------------------------------------------------------------ telefono

    def _mobile_page(self) -> str:
        try:
            return (HUD_DIR / "mobile.html").read_text(encoding="utf-8")
        except OSError:
            return "JARVIS"

    def _remote_handler(self, text: str, as_json: bool, reply) -> None:
        self.send({"type": "user", "text": "TELEFONO // " + text})
        if not as_json:
            ActionLog.add("PHONE", f"Comando dal telefono: {text[:60]}")

        def done(out: str) -> None:
            if not as_json:
                return reply(out)
            r = self.last_turn
            o = {"reply": out, "seconds": time.time() - self.last_started, "local": r.local if r else True,
                 "model": r.tier.value if r else "", "cost": r.cost_usd if r else 0, "output": r.output_tokens if r else 0,
                 "context": (r.input_tokens + r.cache_read + r.cache_write) if r else 0,
                 "cacheRead": r.cache_read if r else 0, "pending": bool(r and r.pending_confirm)}
            reply(json.dumps(o))

        self.command(text, speak=False, completion=done)

    def toggle_remote(self) -> None:
        if self.remote.is_running:
            self.remote.stop()
            self.prefs.set("remote", False)
            self._menu_changed()
            return
        try:
            self.remote.start()
        except OSError as e:
            self.send({"type": "reply", "text": f"Impossibile avviare il server per il telefono: {e}"})
            return
        self.prefs.set("remote", True)
        self._menu_changed()
        self.show_remote_info()

    def show_remote_info(self) -> None:
        ips = local_addresses()
        host = ips[0] if ips else "localhost"
        url = self.remote.url(host)
        try:
            png = Paths.support / "telefono_qr.png"
            qr_png(url, png)
            if IS_WINDOWS:
                os.startfile(str(png))  # type: ignore[attr-defined]
        except Exception:
            pass
        self._copy(url)
        self.send({"type": "reply", "text": (
            f"Server telefono attivo. Link copiato negli appunti: {url}  "
            "Telefono sulla stessa rete Wi-Fi: inquadra il codice QR o apri il link, poi 'Aggiungi alla schermata Home'. "
            "Se Windows chiede di consentire l'accesso in rete, scegli 'Reti private'. "
            "Fuori casa usa Tailscale. Attenzione: la connessione è HTTP in chiaro.")})

    @staticmethod
    def _copy(text: str) -> None:
        if IS_WINDOWS:
            try:
                subprocess.run(["clip.exe"], input=text.encode("utf-16le"), timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass

    # ------------------------------------------------------------------ account Claude / Google

    def refresh_claude_account(self) -> None:
        if time.time() - self.claude_account_at < 60:
            return
        self.claude_account_at = time.time()

        def work():
            from ..bridge import ClaudeSession
            self.claude_account = ClaudeSession.account_status()
            self._menu_changed()
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _terminal(cmd: list[str]) -> None:
        """Apre una finestra del terminale con il comando (login Claude / Google: li fa l'utente, non JARVIS)."""
        if IS_WINDOWS:
            subprocess.Popen(["cmd.exe", "/k", *cmd], creationflags=subprocess.CREATE_NEW_CONSOLE)

    def claude_login(self) -> None:
        installed = self.claude_account[0] if self.claude_account else True
        if not installed:
            self.send({"type": "reply", "text": "Claude Code non è installato: segui l'installazione nel README, poi riapri il menu."})
            return
        self._terminal(["claude", "auth", "login"])
        self.claude_account_at = 0

    def show_voice_guide(self) -> None:
        self.show()
        self.send({"type": "reply", "text": permissions.VOICE_GUIDE})
        permissions.open_settings("ms-settings:speech")

    def google_login(self) -> None:
        self._terminal(["jarvis", "google", "login"])

    # ------------------------------------------------------------------ scorciatoie e finestra attiva

    def _register_hotkeys(self) -> None:
        try:
            import keyboard
            # Alt+Spazio non si usa: su Windows apre il menu della finestra attiva (e PowerToys Run).
            keyboard.add_hotkey("ctrl+shift+j", self.toggle)
            keyboard.add_hotkey("alt+shift+space", lambda: (self.show(), self.toggle_mic()), suppress=True)
        except Exception as e:
            ActionLog.add("SYS", f"Scorciatoie globali non attive ({type(e).__name__})")

    def _track_foreground(self) -> None:
        """Ricorda la finestra usata prima di JARVIS, cosi' "cosa c'e' sullo schermo" cattura quella."""
        if not IS_WINDOWS:
            return
        import psutil
        from .. import winapi
        last = None
        me = os.getpid()
        while True:
            time.sleep(0.5)
            try:
                fg = winapi.foreground_window()
                if not fg or fg[2] == me or "j.a.r.v.i.s" in fg[1].lower() or fg[0] == last:
                    continue
                last = fg[0]
                try:
                    name = Path(psutil.Process(fg[2]).name()).stem
                except psutil.Error:
                    name = fg[1]
                Store.save("frontmost.json", {"hwnd": fg[0], "name": name})
            except Exception:
                pass

    # ------------------------------------------------------------------ icona nella barra e menu

    def _tray_image(self):
        from PIL import Image, ImageDraw
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, size - 4, size - 4), fill=(5, 9, 15, 255), outline=(0, 229, 255, 255), width=4)
        d.ellipse((20, 20, size - 20, size - 20), outline=(0, 229, 255, 255), width=3)
        d.ellipse((28, 28, size - 28, size - 28), fill=(0, 229, 255, 255))
        return img

    def _build_tray(self) -> None:
        import pystray
        from pystray import Menu, MenuItem as Item

        def models():
            yield Item("Automatico (Haiku, sale da solo se serve)", lambda i, it: self.set_model(None),
                       checked=lambda it: self.brain.preferred_tier is None, radio=True)
            desc = {Tier.haiku: "Haiku  · veloce, costo minimo", Tier.sonnet: "Sonnet  · analisi, testi, codice",
                    Tier.opus: "Opus  · ragionamento profondo", Tier.fable: "Fable  · massima capacità, costo più alto"}
            for t in Tier:
                yield Item(desc[t], (lambda tt: lambda i, it: self.set_model(tt))(t),
                           checked=(lambda tt: lambda it: self.brain.preferred_tier == tt)(t), radio=True)

        def efforts():
            yield Item("Automatico (low / medium / high per modello)", lambda i, it: self.set_effort(None),
                       checked=lambda it: self.brain.effort is None, radio=True)
            for e in JarvisBrain.EFFORTS:
                yield Item(e, (lambda ee: lambda i, it: self.set_effort(ee))(e),
                           checked=(lambda ee: lambda it: self.brain.effort == ee)(e), radio=True)

        def modules():
            for m in Module:
                yield Item(m.label, (lambda mm: lambda i, it: self.toggle_module(mm))(m),
                           checked=(lambda mm: lambda it: Modules.is_enabled(mm))(m))

        def voices():
            yield Item("Parla ora  (Alt+Maiusc+Spazio)", lambda i, it: (self.show(), self.toggle_mic()))
            yield Item("Risposte vocali", lambda i, it: self._toggle_pref("voiceReplies", True),
                       checked=lambda it: self.voice_replies)
            yield Item('Ascolto continuo "Jarvis"', lambda i, it: self.toggle_hotword(),
                       checked=lambda it: self.listener.hotword)
            if not find_model():
                yield Item("Modello vocale mancante: esegui `jarvis setup-voice`", None, enabled=False)
            yield Item("Scarica voci italiane migliori...", lambda i, it: self.show_voice_guide())
            yield Menu.SEPARATOR
            for vid, name in self.speech.voices():
                yield Item(f"Voce: {name}", (lambda v: lambda i, it: self.set_voice(v))(vid),
                           checked=(lambda v: lambda it: self.prefs.get("voiceID") == v)(vid), radio=True)

        def initiative():
            yield Item("Briefing adesso", lambda i, it: self.briefing_now())
            yield Item(lambda it: f"Briefing automatico al mattino (dalle {self.prefs.get('proBriefingHour', 7)}:00)",
                       lambda i, it: self._toggle_pref("proBriefing", True),
                       checked=lambda it: self.prefs.get("proBriefing", True))
            yield Item("Avvisa 15 minuti prima degli impegni",
                       lambda i, it: self._toggle_pref("proMeetings", True),
                       checked=lambda it: self.prefs.get("proMeetings", True))
            yield Item("Avvisa con batteria bassa",
                       lambda i, it: self._toggle_pref("proBattery", True),
                       checked=lambda it: self.prefs.get("proBattery", True))

        def phone():
            yield Item("Accesso dal telefono attivo", lambda i, it: self.toggle_remote(), checked=lambda it: self.remote.is_running)
            yield Item("Collega telefono (codice QR)...", lambda i, it: self.show_remote_info(), enabled=lambda it: self.remote.is_running)

        def perms():
            for p in permissions.all_permissions():
                page = p.settings
                if p.name == "Account Google" and not p.ok:
                    action = lambda i, it: self.google_login()
                elif p.name == "Modello vocale italiano" and not p.ok:
                    action = lambda i, it: self._terminal(["jarvis", "setup-voice"])
                elif page:
                    action = (lambda pg: lambda i, it: permissions.open_settings(pg))(page)
                else:
                    action = None
                yield Item(permissions.label(p), action, enabled=action is not None)
            yield Menu.SEPARATOR
            yield Item("Voci italiane migliori...", lambda i, it: self.show_voice_guide())
            yield Item("Diagnostica completa (jarvis doctor)", lambda i, it: self._terminal(["jarvis", "doctor"]))

        def accounts():
            yield Item(lambda it: self._claude_label(), lambda i, it: self.claude_login())
            yield Item("Collega account Google...", lambda i, it: self.google_login())
            yield Item("Scarica modello vocale...", lambda i, it: self._terminal(["jarvis", "setup-voice"]))

        def build():
            self.refresh_claude_account()
            yield Item(lambda it: f"J.A.R.V.I.S.  //  {'in elaborazione' if self.busy else 'online'}", None, enabled=False)
            yield Menu.SEPARATOR
            yield Item("Apri J.A.R.V.I.S.  (Ctrl+Maiusc+J)", lambda i, it: self.show(), default=True)
            yield Item("Nascondi finestra", lambda i, it: self.hide(), enabled=lambda it: self.visible)
            yield Menu.SEPARATOR
            yield Item("Modello", Menu(models))
            yield Item("Effort", Menu(efforts))
            yield Item("Moduli", Menu(modules))
            yield Item("Voce", Menu(voices))
            yield Item("Iniziativa", Menu(initiative))
            yield Item("Telefono", Menu(phone))
            yield Item("Account", Menu(accounts))
            yield Item("Permessi e configurazione", Menu(perms))
            yield Menu.SEPARATOR
            yield Item("Nuova conversazione", lambda i, it: self.reset_sessions())
            yield Item("Sempre in primo piano", lambda i, it: self.toggle_on_top(), checked=lambda it: bool(self.prefs.get("alwaysOnTop", False)))
            yield Item("Avvia all'accesso", lambda i, it: self.toggle_autostart(), checked=lambda it: self.autostart_enabled())
            yield Item(lambda it: f"Sessione: {self.turns} turni  ·  ${self.cost:.4f}", None, enabled=False)
            yield Menu.SEPARATOR
            yield Item("Apri cartella dati", lambda i, it: os.startfile(str(Paths.support)) if IS_WINDOWS else None)
            yield Item("Ricarica interfaccia", lambda i, it: self.reload_hud())
            yield Menu.SEPARATOR
            yield Item("Chiudi J.A.R.V.I.S.", lambda i, it: self.quit())

        self.icon = pystray.Icon("JARVIS", self._tray_image(), "J.A.R.V.I.S.", Menu(build))
        self.icon.run_detached()

    def _claude_label(self) -> str:
        a = self.claude_account
        if a is None:
            return "Account Claude: verifica..."
        if not a[0]:
            return "Claude Code non installato..."
        if not a[1]:
            return "Account Claude: non collegato (clic per collegare)..."
        return "Account Claude: " + (a[2] or "collegato").capitalize()

    # ------------------------------------------------------------------ azioni di menu

    def _menu_changed(self) -> None:
        """Ricostruisce il menu della barra: spunte e testi dinamici si aggiornano solo cosi'."""
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def _toggle_pref(self, key: str, default: bool) -> None:
        self.prefs.set(key, not self.prefs.get(key, default))
        self._menu_changed()

    def set_model(self, tier: Tier | None) -> None:
        self.prefs.set("tier", tier.value if tier else None)
        self.brain.preferred_tier = tier
        self._settings_changed(f"Modello: {tier.value.capitalize() if tier else 'automatico'}.")
        self._menu_changed()

    def set_effort(self, effort: str | None) -> None:
        self.prefs.set("effort", effort)
        self.brain.effort = effort
        self._settings_changed(f"Effort: {effort or 'automatico'}.")
        self._menu_changed()

    def _settings_changed(self, msg: str) -> None:
        self.send({"type": "model", "label": self.model_label()})
        self.send({"type": "reply", "text": msg + " Nuova conversazione avviata."})
        self.send({"type": "feed", "module": "SYS", "text": msg})

    def toggle_module(self, m: Module) -> None:
        on = not Modules.is_enabled(m)
        Modules.set(m, on)
        # le nuove sessioni ricevono istruzioni con/senza i comandi del modulo
        threading.Thread(target=lambda: (self.brain.shutdown(), self.brain.prewarm()), daemon=True).start()
        ActionLog.add("SYS", f"Modulo {m.label} {'attivato' if on else 'disattivato'}")
        self.poll_feed()
        self._menu_changed()

    def toggle_hotword(self) -> None:
        on = not self.listener.hotword
        self.listener.set_hotword(on)
        self.prefs.set("hotword", self.listener.hotword)
        if self.listener.hotword == on:
            self.send({"type": "reply", "text": 'Ascolto continuo attivo: dica "Jarvis" seguito dal comando.' if on
                       else "Ascolto continuo disattivato."})
        self._menu_changed()

    def set_voice(self, vid: str) -> None:
        self.prefs.set("voiceID", vid)
        self.speech.set_voice(vid)
        self.speech.speak("Questa è la mia nuova voce, signore.")
        self._menu_changed()

    def reset_sessions(self) -> None:
        def work():
            self.brain.shutdown()
            self.turns, self.cost, self.last_context = 0, 0.0, 0
            self.send_stats("--")
            self.send({"type": "reply", "text": "Nuova conversazione avviata."})
            self.brain.prewarm()
        threading.Thread(target=work, daemon=True).start()

    def toggle_on_top(self) -> None:
        v = not bool(self.prefs.get("alwaysOnTop", False))
        self.prefs.set("alwaysOnTop", v)
        try:
            self.window.on_top = v
        except Exception:
            pass
        self._menu_changed()

    def reload_hud(self) -> None:
        self.hud_ready = False
        try:
            self.window.load_url(str(HUD_DIR / "index.html"))
        except Exception:
            pass

    @staticmethod
    def _run_command() -> str:
        cmd = Paths.command()
        return " ".join(f'"{c}"' if " " in c else c for c in cmd + ["hud"])

    def autostart_enabled(self) -> bool:
        if not IS_WINDOWS:
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, "JARVIS")
            return True
        except OSError:
            return False

    def toggle_autostart(self) -> None:
        if not IS_WINDOWS:
            return
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if self.autostart_enabled():
                winreg.DeleteValue(k, "JARVIS")
            else:
                winreg.SetValueEx(k, "JARVIS", 0, winreg.REG_SZ, self._run_command())
        self._menu_changed()

    def quit(self) -> None:
        self._quitting = True
        self._tick_stop.set()
        self.proactive.stop()
        self.speech.stop()
        self.listener.set_hotword(False)
        self.remote.stop()
        self.brain.shutdown()
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        if self.icon:
            self.icon.stop()
        try:
            self.window.destroy()
        except Exception:
            pass


def main() -> int:
    if not IS_WINDOWS:
        print("L'interfaccia grafica di JARVIS per Windows funziona solo su Windows.")
        return 1
    # se un'altra istanza e' gia' aperta non ne avvio una seconda (scorciatoie e microfono si pesterebbero i piedi)
    import ctypes
    mutex = ctypes.WinDLL("kernel32", use_last_error=True).CreateMutexW(None, False, "Local\\JARVIS_HUD_SINGLETON")
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        return 0
    App.mutex = mutex          # il mutex vive finche' vive il processo
    return App().run()
