"""Test offline di JARVIS per Windows: non servono Windows, account Google, Claude ne' rete.

    python -m pytest windows/tests        (oppure: python -m unittest discover -s windows/tests)

Coprono la logica pura: router, date, riferimenti, conferme, limite d'output, moduli, note, file, documenti
e il ponte verso Claude (con un finto `claude`). Le parti che dipendono da Windows o da Google (volume, tray,
Calendar, Gmail...) si provano solo su un PC Windows con gli account collegati.
"""
import os
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

# Stato e cartelle utente isolati: devono essere impostati PRIMA di importare jarvis.
if "JARVIS_TEST_ROOT" not in os.environ:      # una sola cartella temporanea per tutti i file di test
    _root = tempfile.mkdtemp(prefix="jarvis_test_")
    for k in [k for k in os.environ if k.startswith("JARVIS_")]:
        del os.environ[k]
    os.environ["JARVIS_TEST_ROOT"] = _root
    os.environ["JARVIS_HOME"] = os.path.join(_root, "support")
    os.environ["HOME"] = os.environ["USERPROFILE"] = os.path.join(_root, "home")
    os.makedirs(os.environ["HOME"], exist_ok=True)
_TMP = os.environ["JARVIS_TEST_ROOT"]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis import cli, gate, prompt  # noqa: E402
from jarvis.core import Args, Refs, Store, When  # noqa: E402
from jarvis.modules import Module, Modules  # noqa: E402
from jarvis.router import Router, Tier  # noqa: E402
from jarvis.turnlog import OutputCap  # noqa: E402


def tier_of(text: str) -> str:
    r = Router.route(text)
    return r.tier.value if r.kind == "model" else r.kind


class RouterTests(unittest.TestCase):
    def test_tiers(self):
        cases = [
            ("ciao, come stai?", "haiku"),
            ("che tempo farà domani a Milano", "haiku"),
            ("spiegami in dettaglio come funziona l'inflazione", "sonnet"),
            ("parola " * 120, "sonnet"),
            ("ragiona a fondo sulla strategia migliore", "sonnet"),   # ex hint opus: sale solo a Sonnet
            ("/opus ciao", "opus"),
            ("/fable ciao", "fable"),
            ("/sonnet ciao", "sonnet"),
            ("/haiku ciao", "haiku"),
        ]
        for text, want in cases:
            self.assertEqual(tier_of(text), want, text)

    def test_fast_paths(self):
        cases = {
            "metti un timer di 20 minuti": ["timer", "20 minuti"],
            "timer 1 ora e 30 minuti": ["timer", "1 ora30 minuti"],
            "alza il volume": ["sys", "volume", "su"],
            "abbassa il volume": ["sys", "volume", "giu"],
            "metti il volume al 40%": ["sys", "volume", "40"],
            "muto": ["sys", "volume", "muto"],
            "a quanto è il volume": ["sys", "volume"],
            "alza la luminosità": ["sys", "brightness", "su"],
            "batteria": ["sys", "battery"],
            "blocca il pc": ["sys", "lock"],
            "attiva la modalità scura": ["sys", "dark", "on"],
            "fai uno screenshot": ["sys", "screenshot"],
            "metti una sveglia alle 7:30": ["alarm", "set", "07:30"],
            "sveglia alle 6": ["alarm", "set", "06:00"],
            "quali sveglie ho": ["alarm", "list"],
            "pausa": ["music", "pause"],
            "riproduci": ["music", "play"],
            "prossima canzone": ["music", "next"],
            "che canzone è": ["music", "now"],
            "annulla il timer": ["timer", "cancel"],
            "ehi jarvis, batteria": ["sys", "battery"],
        }
        for text, argv in cases.items():
            r = Router.route(text)
            self.assertEqual((r.kind, r.argv), ("local", argv), text)

    def test_answers(self):
        self.assertEqual(Router.route("che ore sono").kind, "answer")
        self.assertIn("Oggi è", Router.route("che giorno è oggi").text)

    def test_briefing_is_haiku_without_whatsapp(self):
        r = Router.route("briefing")
        self.assertEqual((r.kind, r.tier), ("model", Tier.haiku))
        self.assertIn("jarvis cal list oggi", r.text)
        self.assertNotIn("wa ", r.text)
        self.assertNotRegex(r.text.lower(), r"notizi|borsa")

    def test_confirmation_only_with_pending(self):
        self.assertEqual(Router.route("sì", has_pending=True).argv, ["confirm"])
        self.assertEqual(Router.route("annulla", has_pending=True).argv, ["cancel"])
        self.assertNotEqual(Router.route("sì", has_pending=False).kind, "local")

    def test_vision(self):
        self.assertTrue(Router.needs_vision("cosa c'è sullo schermo?"))
        self.assertFalse(Router.needs_vision("che ore sono"))


class DateTests(unittest.TestCase):
    def test_parse(self):
        d, t = When.parse("2026-11-18 16:30")
        self.assertEqual((d.year, d.month, d.day, d.hour, d.minute, t), (2026, 11, 18, 16, 30, True))
        d, t = When.parse("18/11 9:05")
        self.assertEqual((d.month, d.day, d.hour, d.minute), (11, 18, 9, 5))
        d, t = When.parse("domani 15")
        self.assertEqual((d.hour, t), (15, True))
        d, t = When.parse("oggi")
        self.assertFalse(t)
        self.assertIsNone(When.parse("blabla"))
        self.assertIsNone(When.parse("25:00"))
        d, _ = When.parse("lunedì 9:00")
        self.assertEqual((d.weekday(), d.hour), (0, 9))

    def test_duration(self):
        self.assertEqual(When.duration("20m"), 1200)
        self.assertEqual(When.duration("90s"), 90)
        self.assertEqual(When.duration("1h30m"), 5400)
        self.assertEqual(When.duration("20"), 1200)
        self.assertEqual(When.duration("1 ora"), 3600)
        self.assertIsNone(When.duration("boh"))

    def test_format(self):
        self.assertEqual(When.duration_text(5400), "1 ora e 30 minuti")
        self.assertEqual(When.duration_text(61), "1 minuto e 1 secondo")


class StateTests(unittest.TestCase):
    def test_refs(self):
        labels = Refs.assign("e", ["a", "b"])
        self.assertEqual(labels, ["e1", "e2"])
        self.assertEqual(Refs.resolve("[e2]"), "b")
        Refs.assign("e", ["c"])                      # sostituisce l'elenco precedente
        self.assertIsNone(Refs.resolve("e2"))
        Refs.assign("nt", ["x"])                     # un prefisso non cancella l'altro
        self.assertEqual(Refs.resolve("e1"), "c")

    def test_args(self):
        a = Args(["add", "--title", "Ciao", "--daily", "--to", "a@b.it,c@d.it"], flags={"daily"})
        self.assertEqual(a.pos, ["add"])
        self.assertEqual(a.o("title"), "Ciao")
        self.assertTrue(a.has("daily"))
        self.assertEqual(a.list("to"), ["a@b.it", "c@d.it"])

    def test_modules(self):
        self.assertIsNone(Module.for_command("zzz"))
        self.assertEqual(Module.for_command("cal"), Module.calendar)
        Modules.set(Module.music, False)
        out, code = cli.run(["music", "now"])
        self.assertEqual(code, 1)
        self.assertIn("disattivato", out)
        self.assertNotIn("jarvis music", prompt.system())
        Modules.set(Module.music, True)
        self.assertIn("jarvis music", prompt.system())

    def test_stale_module_in_file_is_ignored(self):
        Store.save("modules.json", {"disabled": ["news", "music"]})
        self.assertEqual(Modules.disabled(), {"news", "music"})
        Modules.set(Module.music, True)
        self.assertEqual(Modules.disabled(), set())   # "news" non esiste piu' e sparisce al primo salvataggio


class OutputCapTests(unittest.TestCase):
    def test_cap(self):
        full = cli.run(["help"])[0]
        self.assertGreater(len(full.encode()), 300)
        cut = OutputCap.apply(full, limit=300)
        head, notice = cut.split("\n[OUTPUT TRONCATO")
        self.assertLessEqual(len(head.encode()), 300)
        self.assertTrue(full.startswith(head))
        self.assertIn("omessi", notice)
        self.assertEqual(OutputCap.apply(full, limit=0), full)
        self.assertEqual(OutputCap.apply("breve", limit=300), "breve")

    def test_confirmation_line_survives_truncation(self):
        s = "x" * 500 + "\n" + gate.MARKER + " [p1]: Inviare mail. Chiedi conferma"
        self.assertIn(gate.MARKER, OutputCap.apply(s, limit=100))

    def test_cli_cap_only_for_agent(self):
        env = dict(os.environ, JARVIS_TOOL_OUTPUT_MAX="300", PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        run = lambda extra: subprocess.run([sys.executable, "-m", "jarvis", "help"], capture_output=True, text=True,
                                           env=dict(env, **extra)).stdout
        self.assertNotIn("TRONCATO", run({}))
        self.assertIn("TRONCATO", run({"JARVIS_AGENT": "1"}))

    def test_agent_cannot_confirm(self):
        env = dict(os.environ, JARVIS_AGENT="1", PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        for cmd in ("confirm", "cancel"):
            r = subprocess.run([sys.executable, "-m", "jarvis", cmd], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1)
            self.assertIn("solo dall'interfaccia", r.stdout)


class GateTests(unittest.TestCase):
    def setUp(self):
        gate.cancel_all()

    def test_trash_needs_confirmation(self):
        home = Path(os.environ["HOME"])
        f = home / "da_cestinare.txt"
        f.write_text("x")
        out, code = cli.run(["file", "trash", str(f)])
        self.assertIn(gate.MARKER, out)
        self.assertTrue(f.exists())                   # niente e' successo senza conferma
        self.assertIn("da_cestinare.txt", gate.latest_summary())
        gate.cancel_all()
        self.assertIsNone(gate.latest_id())

    def test_sys_open_path_needs_confirmation(self):
        # Il nome di un'app e' immediato, ma un percorso, un indirizzo o un protocollo potrebbe avviare
        # un eseguibile o uno script scaricato: serve la conferma, come per `file open`.
        for target in (r"C:\Users\me\Downloads\setup.exe", r"\\server\share\x.bat", "https://example.com",
                       "ms-settings:privacy", "..\\x.cmd", "%TEMP%\\a.js", "~/a.vbs"):
            out, _ = cli.run(["sys", "open", target])
            self.assertIn(gate.MARKER, out, target)
            gate.cancel_all()

    def test_cancel(self):
        cli.run(["file", "trash", str(Path(os.environ["HOME"]) / "inesistente.txt")])   # errore: niente richiesta
        self.assertIsNone(gate.latest_id())
        f = Path(os.environ["HOME"]) / "a.txt"
        f.write_text("x")
        cli.run(["file", "trash", str(f)])
        self.assertIn("Annullato", gate.cancel(None))
        self.assertTrue(f.exists())

    def test_expired_request_is_dropped(self):
        f = Path(os.environ["HOME"]) / "b.txt"
        f.write_text("x")
        cli.run(["file", "trash", str(f)])
        items = Store.load("pending.json")
        items[0]["created"] -= gate.TTL + 1
        Store.save("pending.json", items)
        self.assertIsNone(gate.latest_id())


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(os.environ["HOME"])
        self.desk = self.home / "Desktop"
        self.desk.mkdir(exist_ok=True)

    def test_find_move_rename(self):
        (self.desk / "relazione_test.pdf").write_text("pdf finto")
        (self.desk / "Scuola").mkdir(exist_ok=True)
        out, _ = cli.run(["file", "find", "relazione_test", "--in", str(self.desk)])
        self.assertIn("relazione_test.pdf", out)
        self.assertIn("[f1]", out)
        out, code = cli.run(["file", "move", "f1", "--to", str(self.desk / "Scuola")])
        self.assertEqual(code, 0, out)
        self.assertTrue((self.desk / "Scuola" / "relazione_test.pdf").exists())
        out, code = cli.run(["file", "rename", str(self.desk / "Scuola" / "relazione_test.pdf"), "tema"])
        self.assertEqual(code, 0, out)
        self.assertTrue((self.desk / "Scuola" / "tema.pdf").exists())

    def test_sensitive_and_risky_need_confirmation(self):
        (self.desk / "x.txt").write_text("x")
        ssh = self.home / ".ssh"
        ssh.mkdir(exist_ok=True)
        out, _ = cli.run(["file", "move", str(self.desk / "x.txt"), "--to", str(ssh)])
        self.assertIn(gate.MARKER, out)
        (self.desk / "run.bat").write_text("echo hi")
        out, _ = cli.run(["file", "open", str(self.desk / "run.bat")])
        self.assertIn(gate.MARKER, out)
        (ssh / "id_test").write_text("segreto")
        out, _ = cli.run(["file", "copy", str(ssh / "id_test"), "--to", str(self.desk)])
        self.assertIn(gate.MARKER, out)
        self.assertFalse((self.desk / "id_test").exists())
        gate.cancel_all()

    def test_ls_and_mkdir(self):
        out, code = cli.run(["file", "mkdir", str(self.desk / "Nuova")])
        self.assertEqual(code, 0)
        out, _ = cli.run(["file", "ls", str(self.desk)])
        self.assertIn("Nuova", out)

    def test_missing_file_is_an_error_not_a_crash(self):
        out, code = cli.run(["file", "open", str(self.desk / "non_esiste.txt")])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("ERRORE"))


class NotesAndDocsTests(unittest.TestCase):
    def test_notes(self):
        out, code = cli.run(["note", "add", "--title", "Test JARVIS", "--body", "prova uno\\nriga due"])
        self.assertEqual(code, 0, out)
        out, _ = cli.run(["note", "search", "Test JARVIS"])
        self.assertIn("[nt1] Test JARVIS", out)
        out, _ = cli.run(["note", "read", "nt1"])
        self.assertIn("riga due", out)
        out, _ = cli.run(["note", "append", "nt1", "--text", "aggiunta"])
        self.assertIn("aggiunto", out)
        out, _ = cli.run(["note", "read", "nt1"])
        self.assertIn("aggiunta", out)

    def test_note_ref_cannot_escape_notes_folder(self):
        Refs.assign("nt", ["../../fuori.md"])
        out, code = cli.run(["note", "read", "nt1"])
        self.assertEqual(code, 1)

    def test_doc_text_and_docx(self):
        home = Path(os.environ["HOME"])
        (home / "t.txt").write_text("ciao dal testo", encoding="utf-8")
        out, _ = cli.run(["doc", "read", str(home / "t.txt")])
        self.assertIn("ciao dal testo", out)
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx non installato")
        d = Document()
        d.add_paragraph("Fotosintesi clorofilliana")
        d.save(home / "t.docx")
        out, _ = cli.run(["doc", "read", str(home / "t.docx")])
        self.assertIn("Fotosintesi", out)

    def test_doc_pdf(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf non installato")
        home = Path(os.environ["HOME"])
        w = PdfWriter()
        w.add_blank_page(200, 200)
        with open(home / "vuoto.pdf", "wb") as f:
            w.write(f)
        out, code = cli.run(["doc", "read", str(home / "vuoto.pdf")])
        self.assertEqual(code, 0, out)

    def test_unsupported_format(self):
        home = Path(os.environ["HOME"])
        (home / "x.doc").write_bytes(b"\xd0\xcf\x11\xe0")
        out, code = cli.run(["doc", "read", str(home / "x.doc")])
        self.assertEqual(code, 1)
        self.assertIn("non supportato", out)


class WhatsAppTests(unittest.TestCase):
    def test_send_needs_confirmation_and_reading_is_declared_unsupported(self):
        gate.cancel_all()
        out, code = cli.run(["wa", "send", "--to", "+39 333 1234567", "--text", "prova"])
        self.assertIn(gate.MARKER, out)
        self.assertIn("prova", gate.latest_summary())
        gate.cancel_all()
        out, code = cli.run(["wa", "unread"])
        self.assertEqual(code, 1)
        self.assertIn("non disponibile su Windows", out)

    def test_number_normalisation(self):
        from jarvis.tools.whatsapp import normalize
        self.assertEqual(normalize("+39 333 123 4567"), "393331234567")
        self.assertEqual(normalize("0039 333 1234567"), "393331234567")
        self.assertEqual(normalize("333 1234567"), "393331234567")


class CliTests(unittest.TestCase):
    def test_unknown_and_help(self):
        out, code = cli.run(["boh"])
        self.assertEqual(code, 1)
        self.assertIn("sconosciuto", out)
        self.assertEqual(cli.run([])[1], 0)

    def test_usage_has_no_removed_features(self):
        low = cli.USAGE.lower()
        for word in ("news", "notizie", "apple music", "--app"):
            self.assertNotIn(word, low)

    def test_system_prompt_is_for_windows(self):
        s = prompt.system()
        self.assertIn("PC Windows", s)
        self.assertNotIn("Mac", s)
        self.assertNotRegex(s.lower(), r"notizi")

    def test_timer_validation(self):
        out, code = cli.run(["timer", "boh"])
        self.assertEqual(code, 1)
        out, code = cli.run(["timer", "99999999999999999999h"])
        self.assertEqual(code, 1)


STUB = textwrap.dedent('''\
    #!/usr/bin/env python3
    """Finto `claude`: legge i messaggi stream-json e risponde come farebbe la CLI."""
    import json, sys
    if sys.argv[1:3] == ["auth", "status"]:
        print(json.dumps({"loggedIn": True, "subscriptionType": "pro"})); sys.exit(0)
    print(json.dumps({"type": "system", "subtype": "init", "model": "stub-model", "session_id": "s1"}), flush=True)
    for line in sys.stdin:
        msg = json.loads(line)
        text = msg["message"]["content"][0]["text"]
        if "CRASH" in text:
            sys.exit(3)
        pending = "conferma" in text
        print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "jarvis now"}}]}}), flush=True)
        print(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": ("IN ATTESA DI CONFERMA [p1]: Test. Chiedi conferma" if pending else "ok")}]}}), flush=True)
        print(json.dumps({"type": "result", "result": "(ora attuale: x) Risposta " + str(len(text)), "is_error": False,
                          "total_cost_usd": 0.01, "duration_ms": 5, "usage": {"input_tokens": 3, "output_tokens": 4}}), flush=True)
''')


@unittest.skipIf(sys.platform == "win32", "il finto claude e' uno script Python eseguibile: prova su macOS o Linux")
class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub = Path(_TMP) / "claude_stub.py"
        cls.stub.write_text(STUB)
        cls.stub.chmod(cls.stub.stat().st_mode | stat.S_IEXEC)
        os.environ["JARVIS_CLAUDE"] = str(cls.stub)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("JARVIS_CLAUDE", None)

    def ask(self, brain, text, timeout=15):
        events, done = [], threading.Event()

        def cb(ev):
            events.append(ev)
            if ev.kind == "done":
                done.set()

        brain.handle(text, cb)
        self.assertTrue(done.wait(timeout), "nessuna risposta dal finto claude")
        return events

    def test_turn_and_event_flow(self):
        from jarvis.bridge import JarvisBrain
        brain = JarvisBrain()
        try:
            ev = self.ask(brain, "ciao jarvis")
            kinds = [e.kind for e in ev]
            self.assertEqual(kinds[0], "thinking")
            self.assertIn("tool", kinds)
            r = ev[-1].value
            self.assertTrue(r.text.startswith("Risposta"), r.text)     # "(ora attuale: ...)" ripulito
            self.assertNotIn("ora attuale", r.text)
            self.assertEqual((r.input_tokens, r.output_tokens), (3, 4))
            self.assertAlmostEqual(r.cost_usd, 0.01)
            r2 = self.ask(brain, "di nuovo")[-1].value
            self.assertAlmostEqual(r2.cost_usd, 0.0, places=6)         # il costo e' cumulativo: conta solo la quota del turno
            self.assertTrue(Path(os.environ["JARVIS_HOME"], "turns.jsonl").exists())
        finally:
            brain.shutdown()

    def test_pending_confirmation_flag(self):
        from jarvis.bridge import JarvisBrain
        brain = JarvisBrain()
        try:
            ev = self.ask(brain, "fai una cosa che richiede conferma")
            self.assertIn("confirmNeeded", [e.kind for e in ev])
            self.assertTrue(ev[-1].value.pending_confirm.startswith("IN ATTESA DI CONFERMA"))
        finally:
            brain.shutdown()

    def test_local_route_costs_no_tokens(self):
        from jarvis.bridge import JarvisBrain
        brain = JarvisBrain()
        ev = self.ask(brain, "che ore sono")
        self.assertTrue(ev[-1].value.local)
        self.assertEqual(brain.sessions, {})                           # nessun processo claude e' partito

    def test_explicit_tier_and_preferred_tier(self):
        from jarvis.bridge import JarvisBrain
        brain = JarvisBrain()
        try:
            brain.preferred_tier = Tier.sonnet
            self.assertEqual(self.ask(brain, "ciao")[-1].value.tier, Tier.sonnet)
            self.assertEqual(self.ask(brain, "/opus ciao")[-1].value.tier, Tier.opus)
        finally:
            brain.shutdown()

    def test_dead_process_is_reported_not_hung(self):
        from jarvis.bridge import JarvisBrain
        brain = JarvisBrain()
        try:
            r = self.ask(brain, "CRASH adesso")[-1].value
            self.assertTrue(r.is_error)
            self.assertIn("interrotto", r.text)
        finally:
            brain.shutdown()

    def test_account_status(self):
        from jarvis.bridge import ClaudeSession
        self.assertEqual(ClaudeSession.account_status(), (True, True, "pro"))

    def test_security_flags_are_not_widened(self):
        src = (Path(__file__).resolve().parents[1] / "jarvis" / "bridge.py").read_text(encoding="utf-8")
        self.assertIn('"--allowedTools", "Bash(jarvis:*)"', src)
        self.assertIn('"--disallowedTools", "Bash(jarvis confirm:*)", "Bash(jarvis cancel:*)"', src)
        self.assertIn('"--permission-mode", "dontAsk"', src)
        self.assertEqual(len(re.findall(r'"--allowedTools"', src)), 1)

    def test_environment_is_clean(self):
        from jarvis.bridge import ClaudeSession
        os.environ["ANTHROPIC_API_KEY"] = "x"
        os.environ["CLAUDE_CODE_FOO"] = "x"
        os.environ["CLAUDE_CODE_GIT_BASH_PATH"] = "C:/Git/bin/bash.exe"
        try:
            env = ClaudeSession.clean_environment()
        finally:
            for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_FOO", "CLAUDE_CODE_GIT_BASH_PATH"):
                os.environ.pop(k, None)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_FOO", env)
        self.assertEqual(env["CLAUDE_CODE_GIT_BASH_PATH"], "C:/Git/bin/bash.exe")   # serve a Claude Code su Windows
        self.assertEqual(env["JARVIS_AGENT"], "1")


class DoctorTests(unittest.TestCase):
    def test_report_runs_and_hides_home(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        r = subprocess.run([sys.executable, "-m", "jarvis", "doctor"], capture_output=True, text=True, env=env)
        self.assertIn("J.A.R.V.I.S. doctor", r.stdout)
        self.assertIn("errori", r.stdout.splitlines()[-1])
        self.assertNotIn(os.environ["HOME"], r.stdout)          # il nome utente non finisce nel report
        self.assertNotRegex(r.stdout, r"Traceback")


class NoLeftoversTests(unittest.TestCase):
    def test_no_news_in_windows_sources(self):
        root = Path(__file__).resolve().parents[1]
        bad = re.compile(r"\bnews\b|notizie|ansa\.it|sole ?24|\brss\b", re.I)
        for p in root.rglob("*"):
            if p.suffix in (".py", ".js", ".html", ".css", ".toml", ".bat", ".md") and "tests" not in p.parts:
                self.assertIsNone(bad.search(p.read_text(encoding="utf-8")), str(p))


class QuickFixTests(unittest.TestCase):
    def test_music_app_names(self):
        from jarvis.tools.music import app_name, describe
        self.assertEqual(app_name("Spotify.exe"), "Spotify")
        self.assertEqual(app_name("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"), "Lettore multimediale")
        self.assertEqual(app_name("MSEdge"), "Edge")
        self.assertEqual(app_name("308046B0AF4A39CB"), "Firefox")
        self.assertEqual(describe({"title": "Yellow", "artist": "Coldplay"}), "Coldplay - Yellow")
        self.assertEqual(describe({"title": "Video", "artist": ""}), "Video")
        self.assertNotIn("spotify)", cli.USAGE.lower())

    def test_permissions_never_raise(self):
        from jarvis import permissions
        perms = permissions.all_permissions()
        self.assertEqual([p.name for p in perms][:2], ["Microfono", "Notifiche"])
        for p in perms:
            self.assertTrue(permissions.label(p).startswith(p.name))
        self.assertIn("Ora e lingua", permissions.VOICE_GUIDE)

    def test_alt_space_not_hijacked(self):
        src = (Path(__file__).resolve().parents[1] / "jarvis" / "app" / "hud.py").read_text(encoding="utf-8")
        self.assertNotIn('add_hotkey("alt+space"', src)
        self.assertIn('add_hotkey("alt+shift+space"', src)


if __name__ == "__main__":
    unittest.main()
