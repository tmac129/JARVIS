"""Verifica del codice Google contro le definizioni ufficiali delle API (documenti di discovery inclusi in
google-api-python-client): le richieste vengono costruite dalla libreria vera, che rifiuta parametri inesistenti.
Le risposte di Google sono simulate: non servono rete ne' account.
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

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

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import HttpMockSequence
    HAVE_GOOGLE = True
except ImportError:
    HAVE_GOOGLE = False

from jarvis import cli, gate  # noqa: E402
from jarvis.core import Refs  # noqa: E402


def J(obj):
    return ({"status": "200", "content-type": "application/json"}, json.dumps(obj))


def patch_service(module, name, version, responses, log):
    """Sostituisce service() con un client reale che risponde con `responses` in ordine e registra le richieste."""
    class Seq(HttpMockSequence):
        def request(self, uri, method="GET", body=None, headers=None, **kw):
            log.append((method, uri, json.loads(body) if body else None))
            return super().request(uri, method, body, headers, **kw)

    module.service = lambda n, v: build(n, v, http=Seq([(r[0], r[1]) for r in responses]), static_discovery=True,
                                        developerKey="x")


@unittest.skipUnless(HAVE_GOOGLE, "google-api-python-client non installato")
class CalendarTests(unittest.TestCase):
    def setUp(self):
        import jarvis.tools.calendar as cal
        self.cal = cal
        self.log = []
        gate.cancel_all()

    def cals(self):
        return J({"items": [{"id": "primary@x", "summary": "Personale", "primary": True, "accessRole": "owner", "selected": True},
                            {"id": "fest@x", "summary": "Festività", "accessRole": "reader", "selected": True}]})

    def test_list_today(self):
        start = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        ev = {"id": "ev1", "summary": "Riunione", "location": "Sala 2", "status": "confirmed",
              "start": {"dateTime": start.astimezone().isoformat()}, "end": {"dateTime": (start + timedelta(hours=1)).astimezone().isoformat()}}
        allday = {"id": "ev2", "summary": "Ferie", "start": {"date": start.date().isoformat()},
                  "end": {"date": (start + timedelta(days=1)).date().isoformat()}}
        patch_service(self.cal, "calendar", "v3", [self.cals(), J({"items": [ev]}), J({"items": [allday]})], self.log)
        out, code = cli.run(["cal", "list", "oggi"])
        self.assertEqual(code, 0, out)
        self.assertIn("2 impegni oggi", out)
        self.assertIn("[e2] 09:00-10:00 Riunione @Sala 2 (Personale)", out)   # il "tutto il giorno" parte a mezzanotte: viene prima
        self.assertIn("[e1] tutto il giorno Ferie (Festività)", out)
        self.assertIn("singleEvents=true", self.log[1][1])
        self.assertIn("orderBy=startTime", self.log[1][1])
        self.assertIsNotNone(Refs.resolve("e2"))

    def test_empty_day(self):
        patch_service(self.cal, "calendar", "v3", [self.cals(), J({"items": []}), J({"items": []})], self.log)
        self.assertEqual(cli.run(["cal", "list", "domani"])[0], "Nessun impegno domani.")

    def test_add_timed_and_all_day(self):
        patch_service(self.cal, "calendar", "v3", [self.cals(), J({"id": "new"})], self.log)
        out, code = cli.run(["cal", "add", "--title", "Dentista", "--start", "domani 15:00", "--min", "45", "--loc", "Via Roma", "--alert", "10"])
        self.assertEqual(code, 0, out)
        self.assertIn('Creato "Dentista"', out)
        body = self.log[-1][2]
        self.assertEqual(body["summary"], "Dentista")
        self.assertEqual(body["location"], "Via Roma")
        s, e = datetime.fromisoformat(body["start"]["dateTime"]), datetime.fromisoformat(body["end"]["dateTime"])
        self.assertEqual(e - s, timedelta(minutes=45))
        self.assertEqual(body["reminders"]["overrides"][0]["minutes"], 10)
        self.assertIn("/calendars/primary%40x/events", self.log[-1][1])   # calendario scrivibile di default
        patch_service(self.cal, "calendar", "v3", [self.cals(), J({"id": "new"})], self.log)
        out, _ = cli.run(["cal", "add", "--title", "Compleanno", "--start", "domani"])
        body = self.log[-1][2]
        self.assertIn("date", body["start"])
        d0, d1 = datetime.fromisoformat(body["start"]["date"]), datetime.fromisoformat(body["end"]["date"])
        self.assertEqual(d1 - d0, timedelta(days=1))                    # in Google la fine e' esclusiva
        self.assertIn("tutto il giorno", out)

    def test_add_rejects_bad_date_and_unknown_calendar(self):
        patch_service(self.cal, "calendar", "v3", [self.cals()], self.log)
        out, code = cli.run(["cal", "add", "--title", "X", "--start", "boh"])
        self.assertEqual(code, 1)
        patch_service(self.cal, "calendar", "v3", [self.cals()], self.log)
        out, code = cli.run(["cal", "add", "--title", "X", "--start", "domani 10:00", "--cal", "Inesistente"])
        self.assertEqual(code, 1)
        self.assertIn("Disponibili: Personale", out)

    def test_delete_requires_confirmation_then_deletes(self):
        st = datetime.now() + timedelta(days=1)
        ev = {"id": "ev9", "summary": "Da togliere", "start": {"dateTime": st.astimezone().isoformat()},
              "end": {"dateTime": (st + timedelta(hours=1)).astimezone().isoformat()}}
        Refs.assign("e", [f"primary@x|ev9|{st.timestamp()}"])
        patch_service(self.cal, "calendar", "v3", [J(ev)], self.log)
        out, _ = cli.run(["cal", "delete", "e1"])
        self.assertIn(gate.MARKER, out)
        self.assertEqual([m for m, *_ in self.log], ["GET"])            # nessuna DELETE prima della conferma
        patch_service(self.cal, "calendar", "v3", [J(ev), ({"status": "204"}, "")], self.log)
        out, code = cli.run(["cal", "delete", "e1"], confirmed=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.log[-1][0], "DELETE")

    def test_move(self):
        st = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
        ev = {"id": "ev3", "summary": "Call", "start": {"dateTime": st.astimezone().isoformat()},
              "end": {"dateTime": (st + timedelta(minutes=30)).astimezone().isoformat()}}
        Refs.assign("e", [f"primary@x|ev3|{st.timestamp()}"])
        patch_service(self.cal, "calendar", "v3", [J(ev), J(ev)], self.log)
        out, code = cli.run(["cal", "move", "e1", "--start", "dopodomani 18:00"])
        self.assertEqual(code, 0, out)
        body = self.log[-1][2]
        a, b = datetime.fromisoformat(body["start"]["dateTime"]), datetime.fromisoformat(body["end"]["dateTime"])
        self.assertEqual(b - a, timedelta(minutes=30))                  # la durata si conserva
        self.assertEqual(self.log[-1][0], "PATCH")

    def test_missing_token_is_a_clear_error(self):
        import importlib
        importlib.reload(importlib.import_module("jarvis.tools.calendar"))
        out, code = cli.run(["cal", "list"])
        self.assertEqual(code, 1)
        self.assertIn("jarvis google login", out)


@unittest.skipUnless(HAVE_GOOGLE, "google-api-python-client non installato")
class TasksTests(unittest.TestCase):
    def setUp(self):
        import jarvis.tools.reminders as rem
        self.rem, self.log = rem, []

    def lists(self):
        return J({"items": [{"id": "L1", "title": "Personali"}, {"id": "L2", "title": "Lavoro"}]})

    def test_add_with_due_time_and_priority(self):
        patch_service(self.rem, "tasks", "v1", [self.lists(), J({"id": "t1"})], self.log)
        out, code = cli.run(["rem", "add", "--title", "Comprare il latte", "--due", "domani 9:00", "--prio", "alta", "--list", "lavoro"])
        self.assertEqual(code, 0, out)
        self.assertIn("aggiunto in Lavoro", out)
        body = self.log[-1][2]
        self.assertEqual(body["title"], "Comprare il latte")
        self.assertTrue(body["due"].endswith("T00:00:00.000Z"))
        self.assertIn("[ore 09:00]", body["notes"])
        self.assertIn("[priorità alta]", body["notes"])
        self.assertIn("/lists/L2/tasks", self.log[-1][1])

    def test_list_sorted_with_marks(self):
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
        items = [{"id": "a", "title": "Senza data", "status": "needsAction"},
                 {"id": "b", "title": "Urgente", "status": "needsAction", "due": tomorrow, "notes": "[ore 09:00] [priorità alta]"}]
        patch_service(self.rem, "tasks", "v1", [self.lists(), J({"items": items}), J({"items": []})], self.log)
        out, code = cli.run(["rem", "list"])
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertEqual(lines[0], "2 da fare:")
        self.assertIn("Urgente", lines[1])                              # con scadenza prima di senza scadenza
        self.assertIn("09:00", lines[1])
        self.assertIn("!", lines[1])
        self.assertIn("Senza data", lines[2])

    def test_done_by_text_and_by_ref(self):
        items = [{"id": "a", "title": "Comprare il latte", "status": "needsAction"}]
        patch_service(self.rem, "tasks", "v1", [self.lists(), J({"items": items}), J({"items": []}), J({"id": "a"})], self.log)
        out, code = cli.run(["rem", "done", "latte"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.log[-1][2], {"status": "completed"})
        Refs.assign("r", ["L1|a"])
        patch_service(self.rem, "tasks", "v1", [J({"id": "a", "title": "Comprare il latte"}), J({"id": "a"})], self.log)
        out, code = cli.run(["rem", "done", "r1"])
        self.assertEqual(code, 0, out)

    def test_done_ambiguous(self):
        items = [{"id": "a", "title": "Latte intero", "status": "needsAction"}, {"id": "b", "title": "Latte di soia", "status": "needsAction"}]
        patch_service(self.rem, "tasks", "v1", [self.lists(), J({"items": items}), J({"items": []})], self.log)
        out, code = cli.run(["rem", "done", "latte"])
        self.assertEqual(code, 1)
        self.assertIn("più promemoria", out)


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


@unittest.skipUnless(HAVE_GOOGLE, "google-api-python-client non installato")
class GmailTests(unittest.TestCase):
    def setUp(self):
        import jarvis.tools.mail as mail
        self.mail, self.log = mail, []
        gate.cancel_all()

    def meta(self, mid, frm, subj, ms):
        return J({"id": mid, "internalDate": str(ms), "payload": {"headers": [{"name": "From", "value": frm}, {"name": "Subject", "value": subj}]}})

    def test_unread(self):
        ms = int(datetime(2026, 11, 20, 8, 30).timestamp() * 1000)
        patch_service(self.mail, "gmail", "v1", [J({"messagesUnread": 12}), J({"messages": [{"id": "aaa111bb"}, {"id": "ccc222dd"}]}),
                                                self.meta("aaa111bb", '"Mario Rossi" <m@x.it>', "Fattura", ms), self.meta("ccc222dd", "Anna <a@x.it>", "Ciao", ms)], self.log)
        out, code = cli.run(["mail", "unread", "2"])
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("12 non lette (mostro 2):"), out)
        self.assertIn("[m1] 2026-11-20 08:30 Mario Rossi: Fattura", out)
        self.assertIn("q=in%3Ainbox+is%3Aunread", self.log[1][1])
        self.assertEqual(Refs.resolve("m2"), "ccc222dd")

    def test_search(self):
        ms = int(datetime(2026, 11, 19, 10, 0).timestamp() * 1000)
        patch_service(self.mail, "gmail", "v1", [J({"messages": [{"id": "abc12345"}], "resultSizeEstimate": 1}), self.meta("abc12345", "Anthropic <x@a.com>", "Receipt", ms)], self.log)
        out, code = cli.run(["mail", "search", "Anthropic"])
        self.assertEqual(code, 0, out)
        self.assertIn("1 risultati", out)
        self.assertIn("Anthropic", out)

    def test_read_marks_as_read(self):
        msg = {"id": "abc12345", "payload": {"headers": [{"name": "From", "value": "A <a@x.it>"}, {"name": "Subject", "value": "Prova"}],
               "mimeType": "multipart/mixed", "parts": [{"mimeType": "text/plain", "body": {"data": b64("Corpo del messaggio")}},
                                                        {"mimeType": "application/pdf", "filename": "doc.pdf", "body": {"attachmentId": "z"}}]}}
        Refs.assign("m", ["abc12345"])
        patch_service(self.mail, "gmail", "v1", [J(msg), J({"id": "abc12345"})], self.log)
        out, code = cli.run(["mail", "read", "m1"])
        self.assertEqual(code, 0, out)
        self.assertIn("Da: A <a@x.it>", out)
        self.assertIn("Allegati: doc.pdf", out)
        self.assertIn("Corpo del messaggio", out)
        self.assertEqual(self.log[-1][2], {"removeLabelIds": ["UNREAD"]})

    def test_send_needs_confirmation_then_sends_with_attachment(self):
        att = Path(os.environ["HOME"]) / "allegato.txt"
        att.write_text("dati")
        argv = ["mail", "send", "--to", "test@example.com", "--subject", "Prova JARVIS", "--body", "ciao\\nmondo", "--attach", str(att)]
        out, _ = cli.run(argv)
        self.assertIn(gate.MARKER, out)
        self.assertIn("allegato.txt", gate.latest_summary())
        self.assertEqual(self.log, [])                                   # nessuna richiesta a Gmail prima del si'
        patch_service(self.mail, "gmail", "v1", [J({"id": "sent"})], self.log)
        out, code = cli.run(argv, confirmed=True)
        self.assertEqual(code, 0, out)
        method, uri, body = self.log[-1]
        self.assertIn("/users/me/messages/send", uri)
        self.assertEqual(method, "POST")
        import email
        import email.policy
        raw = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]), policy=email.policy.default)
        self.assertEqual((raw["To"], raw["Subject"]), ("test@example.com", "Prova JARVIS"))
        self.assertEqual([p.get_filename() for p in raw.walk() if p.get_filename()], ["allegato.txt"])
        self.assertIn("ciao\nmondo", raw.get_body(preferencelist=("plain",)).get_content())

    def test_send_rejects_non_address(self):
        out, code = cli.run(["mail", "send", "--to", "Marco", "--subject", "x", "--body", "y"], confirmed=True)
        self.assertEqual(code, 1)
        self.assertIn("jarvis contact Marco", out)

    def test_draft_creates_draft_without_confirmation(self):
        import webbrowser
        opened = []
        webbrowser.open = lambda u: opened.append(u)
        patch_service(self.mail, "gmail", "v1", [J({"id": "d1"})], self.log)
        out, code = cli.run(["mail", "draft", "--to", "a@b.it", "--subject", "Bozza", "--body", "testo"])
        self.assertEqual(code, 0, out)
        self.assertIn("Bozza pronta in Gmail", out)
        self.assertIn("/users/me/drafts", self.log[-1][1])
        self.assertEqual(self.log[-1][0], "POST")
        self.assertIn("raw", self.log[-1][2]["message"])
        self.assertEqual(opened, ["https://mail.google.com/mail/u/0/#drafts"])

    def test_contacts(self):
        res = {"results": [{"person": {"names": [{"displayName": "Marco Verdi"}], "emailAddresses": [{"value": "marco@x.it"}], "phoneNumbers": [{"value": "+39 333 1234567"}]}}]}
        patch_service(self.mail, "people", "v1", [J({}), J(res)], self.log)
        out, code = cli.run(["contact", "Marco"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out, "Marco Verdi: marco@x.it")
        self.assertIn("readMask=names%2CemailAddresses%2CphoneNumbers", self.log[-1][1])

    def test_whatsapp_recipient_from_google_contacts(self):
        import jarvis.tools.whatsapp as wa
        res = {"results": [{"person": {"names": [{"displayName": "Marco Verdi"}], "phoneNumbers": [{"value": "333 1234567"}]}}]}
        patch_service(self.mail, "people", "v1", [J({}), J(res)], self.log)
        self.assertEqual(wa.resolve_recipient("Marco"), ("Marco Verdi", "393331234567"))


if __name__ == "__main__":
    unittest.main()
