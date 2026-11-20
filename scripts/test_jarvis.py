#!/usr/bin/env python3
"""J.A.R.V.I.S. end-to-end test: talks to the running app (POST /ask.json), so every tool runs
with JARVIS.app's own permissions. Irreversible actions are tested up to the confirmation gate, then cancelled.
Requires macOS, JARVIS.app running and "Accesso da iPhone" enabled (it uses the local HTTP endpoint).
Usage: python3 scripts/test_jarvis.py [--solo offline]
--solo offline: only the checks that need neither the app nor tokens (output cap, model routing)."""
import json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

if sys.platform != "darwin":
    sys.exit("JARVIS funziona solo su macOS: questi test vanno eseguiti sul Mac dove gira JARVIS.app.")

HOME = Path.home()
SUPPORT = HOME / "Library" / "Application Support" / "JARVIS"
OFFLINE_ONLY = "--solo" in sys.argv and "offline" in sys.argv
try:
    TOKEN = json.loads((SUPPORT / "remote.json").read_text())["token"]
except (OSError, ValueError, KeyError):
    TOKEN = None
    if not OFFLINE_ONLY:
        sys.exit(f"Token non trovato in {SUPPORT / 'remote.json'}: avvia JARVIS.app e attiva 'Accesso da iPhone' dal menu.")
URL = "http://127.0.0.1:8787/ask.json"
TEST_DIR = HOME / "Desktop" / "JARVIS_TEST"
results = []


def ask(text, timeout=180):
    req = urllib.request.Request(URL, data=json.dumps({"text": text}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        o = json.loads(r.read().decode())
    o["wall"] = time.time() - t
    return o


def check(name, text, expect=None, local=None, model=None):
    try:
        o = ask(text)
    except Exception as e:
        results.append((name, False, 0, "-", 0, 0.0, f"ERRORE {e}"))
        print(f"FAIL {name}: {e}")
        return {}
    reply = o["reply"]
    ok = True
    if expect and not re.search(expect, reply, re.I | re.S):
        ok = False
    if local is not None and o["local"] != local:
        ok = False
    if model and o["model"] != model:
        ok = False
    m = "locale" if o["local"] else o["model"]
    results.append((name, ok, o["wall"], m, o["context"], o["cost"], reply))
    print(f"{'ok  ' if ok else 'FAIL'} {name:<34} {o['wall']:5.1f}s {m:<7} ctx {o['context']:>6} ${o['cost']:.5f} | {reply[:110]}")
    return o


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def setup_files():
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    for i in (1, 2):
        txt = TEST_DIR / f"relazione{i}.txt"
        txt.write_text(f"Relazione di prova numero {i}. J.A.R.V.I.S. test: la fotosintesi trasforma luce in energia chimica.")
        with open(TEST_DIR / f"relazione{i}.pdf", "wb") as out:
            subprocess.run(["/usr/sbin/cupsfilter", str(txt)], stdout=out, stderr=subprocess.DEVNULL)
        txt.unlink()
    (TEST_DIR / "appunti.txt").write_text("appunti di prova")


JARVIS = Path(os.environ.get("JARVIS_BIN") or HOME / ".local" / "bin" / "jarvis")


def cli(*args, env=None):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run([str(JARVIS), *args], capture_output=True, text=True, timeout=60, env=e)
    return r.returncode, r.stdout + r.stderr


def record(name, ok, detail):
    ok = bool(ok)
    results.append((name, ok, 0, "-", 0, 0.0, detail))
    print(f"{'ok  ' if ok else 'FAIL'} {name:<34} | {detail[:110]}")


TRUNC_NOTICE = "[OUTPUT TRONCATO:"


def offline_tests():
    """Output cap and default model choice: no app, no Claude call, zero tokens."""
    print("== LIMITE OUTPUT TOOL / SCELTA MODELLO (offline)")
    base = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}

    def run(*args, env=None):
        r = subprocess.run([str(JARVIS), *args], capture_output=True, text=True, timeout=30, env=dict(base, **(env or {})))
        return r.stdout

    full = run("help")
    record("help più lungo di 300 byte", len(full.encode()) > 300, f"{len(full.encode())} byte")
    cut = run("help", env={"JARVIS_AGENT": "1", "JARVIS_TOOL_OUTPUT_MAX": "300"})
    head = cut.split(TRUNC_NOTICE)[0]
    record("troncamento: avviso presente", TRUNC_NOTICE in cut, cut[-160:].strip())
    record("troncamento: testo entro il limite", len(head.rstrip("\n").encode()) <= 300, f"{len(head.encode())} byte prima dell'avviso")
    record("troncamento: inizio intatto", full.startswith(head.rstrip("\n")), head[:60])
    record("troncamento: default 6 KB non tocca output brevi",
           run("help", env={"JARVIS_AGENT": "1"}) == full, "help < 6 KB invariato")
    record("troncamento: limite 0 = disattivato",
           run("help", env={"JARVIS_AGENT": "1", "JARVIS_TOOL_OUTPUT_MAX": "0"}) == full, "JARVIS_TOOL_OUTPUT_MAX=0")
    record("troncamento: solo per il modello",
           run("help", env={"JARVIS_TOOL_OUTPUT_MAX": "300"}) == full, "senza JARVIS_AGENT nessun taglio")

    def tier(text):
        m = re.search(r"Tier\.(\w+)", run("route", text))
        return m.group(1) if m else "?"

    for name, text, want in [
        ("default: frase normale -> haiku", "ciao, come stai?", "haiku"),
        ("default: domanda breve -> haiku", "che tempo farà domani a Milano", "haiku"),
        ("escalation hint -> sonnet", "spiegami in dettaglio come funziona l'inflazione", "sonnet"),
        ("testo lungo -> sonnet", "parola " * 120, "sonnet"),
        ("ex hint opus -> sonnet, non opus", "ragiona a fondo sulla strategia migliore", "sonnet"),
        ("/opus esplicito -> opus", "/opus ciao", "opus"),
        ("/fable esplicito -> fable", "/fable ciao", "fable"),
    ]:
        got = tier(text)
        record(name, got == want, f"atteso {want}, ottenuto {got}")


def main():
    t0 = time.time()
    if OFFLINE_ONLY:
        offline_tests()
        return summary(t0)
    setup_files()
    print("== CORSIA LOCALE (0 token)")
    check("ora", "che ore sono", r"Sono le", local=True)
    check("batteria", "batteria", r"Batteria", local=True)
    check("volume (lettura)", "a quanto è il volume", r"Volume|Audio", local=True)
    check("volume su", "alza il volume", r"Volume", local=True)
    check("volume giu", "abbassa il volume", r"Volume", local=True)
    check("luminosità su", "alza la luminosità", r"Luminosit", local=True)
    check("luminosità giu", "abbassa la luminosità", r"Luminosit", local=True)
    check("musica: cosa suona", "che canzone è", r"riproduzione", local=True)
    dark = osa('tell application "System Events" to tell appearance preferences to get dark mode')
    check("modalità scura (invariata)", "attiva la modalità scura" if dark == "true" else "attiva la modalità chiara", r"Modalit", local=True)
    check("apri app", "apri TextEdit", r"Aperta", local=True)
    time.sleep(1.5)
    check("chiudi app", "chiudi TextEdit", r"Chiusa|non è aperta", local=True)
    check("sveglia", "metti una sveglia alle 6:55", r"Sveglia \[a\d+\]", local=True)
    check("elenco sveglie", "quali sveglie ho", r"06:55", local=True)
    check("timer", "metti un timer di 3 secondi", r"Timer", local=True)

    print("== CALENDARIO / PROMEMORIA / SVEGLIE (Haiku)")
    check("impegni oggi", "che impegni ho oggi?", r".")
    check("impegni settimana", "che impegni ho questa settimana?", r".")
    check("crea evento", "crea un evento domani alle 18 chiamato Test JARVIS di 30 minuti", r"Test JARVIS|creat")
    check("sposta evento", "sposta l'evento Test JARVIS di domani alle 19", r"19|spostat")
    check("elimina evento (conferma)", "elimina l'evento Test JARVIS di domani", r"conferm")
    check("conferma", "sì", r"Eliminat", local=True)
    check("promemoria", "ricordami domani alle 9 di comprare il latte test jarvis", r"latte|promemoria")
    check("elenco promemoria", "quali promemoria ho da fare?", r".")
    check("spunta promemoria", "segna come fatto il promemoria del latte test jarvis", r"complet|fatto|segnat")
    check("annulla sveglia", "annulla la sveglia delle 6:55", r"annullat")

    print("== MAIL / WHATSAPP / CONTATTI")
    check("mail non lette", "quante mail non lette ho? dimmi le ultime 3", r"\d")
    check("cerca mail", "cerca le mail di Anthropic", r"Anthropic|mail")
    check("mail con allegato (conferma)", f"manda una mail a test@example.com con oggetto Prova JARVIS, testo ciao, e allega il file relazione1.pdf che sta nella cartella JARVIS_TEST sulla scrivania", r"conferm")
    check("annulla invio", "no", r"Annullat", local=True)
    check("whatsapp non letti", "ho messaggi whatsapp non letti?", r".")
    check("whatsapp chat recenti", "quali sono le mie chat whatsapp più recenti?", r".")
    # fake number: even in the worst case nothing reaches a real person
    check("whatsapp invio (conferma)", "manda un whatsapp al numero +39 000 0000000 con scritto prova", r"conferm|vuole che|procedo")
    check("annulla whatsapp", "annulla", r"Annullat", local=True)
    check("whatsapp di nuovo (conferma)", "manda un whatsapp al numero +39 000 0000000 con scritto prova", r"conferm|vuole che|procedo")
    check("comando intermedio", "che ore sono", r"Sono le", local=True)
    o = check("sì tardivo NON conferma", "sì", r"^(?!.*Inviato).*$")

    print("== FILE / DOCUMENTI / NOTE")
    check("crea cartella", "crea la cartella Scuola dentro JARVIS_TEST sulla scrivania", r"Creat|Scuola")
    check("sposta pdf", "sposta tutti i pdf della cartella JARVIS_TEST sulla scrivania nella sua sottocartella Scuola", r"Spostat|pdf|elementi")
    check("rinomina", "rinomina appunti.txt nella cartella JARVIS_TEST sulla scrivania in note_fisica", r"Rinominat|note_fisica")
    check("cerca file", "trova il file relazione2.pdf", r"relazione2")
    check("leggi documento", "leggi il pdf relazione1 nella cartella JARVIS_TEST/Scuola e dimmi di cosa parla", r"fotosintesi|luce|energia")
    check("cestina (conferma)", "sposta nel cestino note_fisica.txt della cartella JARVIS_TEST sulla scrivania", r"conferm")
    check("conferma cestino", "sì", r"Cestino", local=True)
    check("crea nota", "crea una nota intitolata Test JARVIS con scritto prova di J.A.R.V.I.S.", r"Nota|creat")
    check("cerca nota", "cerca la nota Test JARVIS", r"Test JARVIS|trovat")

    print("== NOTIZIE / SCHERMO / SISTEMA / BRIEFING")
    check("notizie finanza", "notizie importanti di finanza", r".")
    check("notizie italia", "notizie italiane più importanti", r".")
    check("schermo (vision)", "cosa c'è sullo schermo?", r".")
    check("app aperte", "quali app sono aperte?", r".")
    check("briefing", "briefing", r".")
    check("sonnet", "/sonnet in una frase: cos'è l'inflazione?", r"prezz", model="sonnet")

    print("== INIZIATIVA: avviso impegno tra 10 minuti")
    start = time.strftime("%H:%M", time.localtime(time.time() + 600))
    subprocess.run(["open", "-n", "-a", "/Applications/JARVIS.app", "--args", "--run", "cal", "add", "--title",
                    "Test avviso JARVIS", "--start", start, "--min", "15"])
    time.sleep(3)
    log = SUPPORT / "actions.log"
    size = log.stat().st_size
    fired = False
    for _ in range(80):
        time.sleep(1)
        tail = log.read_text(errors="ignore")[size:]
        if "Test avviso JARVIS" in tail and "minuti" in tail:
            fired = True
            break
    results.append(("avviso impegno 15 min", fired, 0, "locale", 0, 0.0, "avviso registrato" if fired else "nessun avviso entro 80s"))
    print(f"{'ok  ' if fired else 'FAIL'} avviso impegno 15 min")
    check("elimina evento avviso", "elimina l'evento Test avviso JARVIS di oggi", r"conferm")
    check("conferma", "sì", r"Eliminat", local=True)

    print("== iPHONE")
    code = urllib.request.urlopen(f"http://127.0.0.1:8787/?token={TOKEN}", timeout=5).status
    results.append(("pagina iPhone", code == 200, 0, "-", 0, 0.0, f"HTTP {code}"))
    print(f"{'ok  ' if code == 200 else 'FAIL'} pagina iPhone HTTP {code}")

    offline_tests()

    # cleanup test data
    osa('tell application "Reminders" to delete (every reminder whose name contains "latte test jarvis")')
    osa('tell application "Notes" to delete (every note of default account whose name is "Test JARVIS")')
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    return summary(t0)


def summary(t0):
    print("\n== RIEPILOGO")
    okc = sum(1 for r in results if r[1])
    model_runs = [r for r in results if r[3] not in ("locale", "-")]
    local_runs = [r for r in results if r[3] == "locale" and r[2] > 0]
    print(f"Superati: {okc}/{len(results)}   durata totale {time.time() - t0:.0f}s")
    if local_runs:
        print(f"Locali (0 token): {len(local_runs)}, tempo medio {sum(r[2] for r in local_runs) / len(local_runs):.2f}s")
    if model_runs:
        print(f"Con Claude: {len(model_runs)}, tempo medio {sum(r[2] for r in model_runs) / len(model_runs):.1f}s, "
              f"costo totale ${sum(r[5] for r in model_runs):.4f}, medio ${sum(r[5] for r in model_runs) / len(model_runs):.5f}")
    fails = [r for r in results if not r[1]]
    for r in fails:
        print(f"  FALLITO: {r[0]} -> {r[6][:200]}")
    (SUPPORT / "test_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
