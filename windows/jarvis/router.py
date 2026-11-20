"""Router a costo zero: comandi frequenti risolti in locale (nessun token), parole chiave per salire di modello."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .core import When


class Tier(str, Enum):
    haiku = "haiku"
    sonnet = "sonnet"
    opus = "opus"
    fable = "fable"

    @property
    def model(self) -> str:
        """Valore per `claude --model`: di default l'alias della CLI (sempre l'ultimo di ogni famiglia).
        Si puo' fissare una versione con JARVIS_MODEL_HAIKU / _SONNET / _OPUS / _FABLE."""
        v = os.environ.get(f"JARVIS_MODEL_{self.value.upper()}", "").strip()
        return v or self.value

    @property
    def effort(self) -> str:
        return {"haiku": "low", "sonnet": "medium"}.get(self.value, "high")

    @property
    def label(self) -> str:
        return {"haiku": "HAIKU [LOW-TOKEN MODE]", "sonnet": "SONNET [ANALYSIS MODE]",
                "opus": "OPUS [DEEP REASONING]", "fable": "FABLE [MAX CAPABILITY]"}[self.value]


@dataclass
class Route:
    kind: str                       # "local" | "answer" | "model"
    argv: list[str] = field(default_factory=list)
    reply: str | None = None
    text: str = ""
    tier: Tier | None = None

    def __str__(self) -> str:
        if self.kind == "local":
            return f"local(argv={self.argv}, reply={self.reply})"
        if self.kind == "answer":
            return f"answer({self.text!r})"
        return f"model({self.tier.value if self.tier else None}, {self.text!r})"


def _local(*argv: str) -> Route:
    return Route("local", argv=list(argv))


# Testo piu' lungo di cosi' (caratteri) va a Sonnet.
SONNET_MIN_CHARS = 600
# Richieste di "ragionamento profondo": salgono solo a Sonnet. Opus e Fable partono solo con "/opus" o "/fable".
OPUS_HINTS = re.compile(r"(ragiona(re)? a fondo|in profondit|approfondit|strategi|piano dettagliato|dimostra(zione)?|architettura|pensaci bene)")
SONNET_HINTS = re.compile(
    r"(codice|script|programm|funzione|debug|\bbug\b|refactor|analizz|analisi|confronta|spiegami|spiega in dettaglio|"
    r"riassumi|riassunto|traduci|scrivi (un|una) (testo|saggio|articolo|tema|lettera|relazione)|"
    r"correggi (il|questo) testo|calcola)")
VISION_HINTS = re.compile(r"(schermo|schermata|screen|cosa (vedi|c'è)|questa finestra|guarda (qui|questo|questa)|immagine|foto|scansion)")

_WAKE_PREFIX = re.compile(r"^(ehi |hey |ok )?jarvis[,!.]?\s*")


class Router:
    @staticmethod
    def route(text_in: str, has_pending: bool = False) -> Route:
        text = text_in.strip()
        low = text.lower()

        # Scelta esplicita del modello: "/fable ...", "/opus ...", "/sonnet ...", "/haiku ..."
        for t in Tier:
            if low.startswith("/" + t.value):
                return Route("model", text=text[len(t.value) + 1:].strip(), tier=t)

        clean = _WAKE_PREFIX.sub("", low).strip(" .!?")

        # Conferma di un'azione critica in attesa
        if has_pending:
            if re.fullmatch(r"(sì|si|conferma|confermo|procedi|vai|ok|okay|invia|fallo|esegui)( pure)?", clean):
                return _local("confirm")
            if re.fullmatch(r"(no|annulla|lascia stare|ferma|stop|non farlo)", clean):
                return _local("cancel")

        r = Router.fast_path(clean)
        if r:
            return r

        # Briefing
        if re.fullmatch(r"(fammi (il )?|dammi (il )?)?briefing( del mattino| di oggi)?|buongiorno( jarvis)?|aggiornami( sulla giornata)?", clean):
            from . import prompt
            return Route("model", text=prompt.briefing(), tier=Tier.haiku)

        # Ora e data
        if re.fullmatch(r"(che ore sono|che ora è|dimmi l'ora|ora esatta)", clean):
            return Route("answer", text=f"Sono le {When.hm(datetime.now())}.")
        if re.fullmatch(r"(che giorno è( oggi)?|che data è( oggi)?|quanti ne abbiamo( oggi)?)", clean):
            return Route("answer", text=f"Oggi è {When.fmt(datetime.now(), time_=False)}.")

        # Timer: "metti un timer di 20 minuti", "timer 1 ora e 30 minuti"
        m = re.fullmatch(r"(?:metti|imposta|avvia|fai partire)?\s*(?:un )?timer (?:di |da )?((?:\d+(?:[.,]\d+)?\s*"
                         r"(?:ore|ora|h|minuti|minuto|min|m|secondi|secondo|sec|s)\s*(?:e\s*)?)+)", clean)
        if m:
            spec = m[1].replace(" e ", "")
            if When.duration(spec) is not None:
                return _local("timer", spec)
        if re.fullmatch(r"(annulla|ferma|stop) (il )?timer", clean):
            return _local("timer", "cancel")

        # Salita di modello (Haiku -> Sonnet; mai Opus/Fable da soli)
        if OPUS_HINTS.search(clean) or SONNET_HINTS.search(clean) or len(text) > SONNET_MIN_CHARS:
            return Route("model", text=text, tier=Tier.sonnet)
        return Route("model", text=text, tier=Tier.haiku)

    @staticmethod
    def needs_vision(text: str) -> bool:
        return VISION_HINTS.search(text.lower()) is not None

    @staticmethod
    def fast_path(c: str) -> Route | None:
        """Comandi quotidiani gestiti in locale: istantanei, zero token."""
        fm = re.fullmatch
        # musica
        if fm(r"(metti in )?pausa( la musica)?|ferma la musica|stop (alla )?musica|pausa musica", c):
            return _local("music", "pause")
        if fm(r"(riprendi|fai ripartire|continua|riavvia)( la)? musica|play|riproduci|metti (un po' di )?musica", c):
            return _local("music", "play")
        if fm(r"(prossim[ao]|(canzone|brano|traccia) successiv[ao]|salta( (la )?(canzone|brano))?|next|cambia canzone)( canzone| brano)?", c):
            return _local("music", "next")
        if fm(r"((canzone|brano|traccia) precedente|torna alla canzone precedente|indietro di una canzone)", c):
            return _local("music", "prev")
        if fm(r"(che|quale) (canzone|brano|pezzo) (è|sta suonando|suona)( questo| questa)?|cosa sta suonando|che canzone è", c):
            return _local("music", "now")
        # volume
        if fm(r"(alza|aumenta)( (un po'|il|l'))?( volume| audio)?( (un po'|di più))?", c) and ("volume" in c or "audio" in c):
            return _local("sys", "volume", "su")
        if fm(r"(abbassa|diminuisci)( (un po'|il|l'))?( volume| audio)?( (un po'|di più))?", c) and ("volume" in c or "audio" in c):
            return _local("sys", "volume", "giu")
        m = fm(r"(metti |imposta )?(il )?volume (a|al) (\d{1,3})( ?%| per ?cento)?", c)
        if m:
            return _local("sys", "volume", m[4])
        if fm(r"(togli|disattiva|silenzia) (l'audio|il volume|l'audio del (mac|pc|computer))|muto|silenzio|modalità muto", c):
            return _local("sys", "volume", "muto")
        if fm(r"(riattiva|rimetti) (l'audio|il volume)", c):
            return _local("sys", "volume", "attiva")
        if fm(r"(a quanto è|qual è|quanto è alto) il volume", c):
            return _local("sys", "volume")
        # luminosita'
        if fm(r"(alza|aumenta) (la )?luminosità", c):
            return _local("sys", "brightness", "su")
        if fm(r"(abbassa|diminuisci) (la )?luminosità", c):
            return _local("sys", "brightness", "giu")
        m = fm(r"(metti |imposta )?(la )?luminosità (a|al) (\d{1,3})( ?%| per ?cento)?", c)
        if m:
            return _local("sys", "brightness", m[4])
        # sistema
        if fm(r"(quanta |livello (della |di )?|stato (della )?|com'è la |come sta la )?batteria( rimasta| residua)?", c):
            return _local("sys", "battery")
        if fm(r"blocca (lo schermo|il mac|il pc|il computer)", c):
            return _local("sys", "lock")
        if fm(r"(attiva|metti|passa a)( la)? (modalità scura|tema scuro|dark mode)", c):
            return _local("sys", "dark", "on")
        if fm(r"(attiva|metti|passa a)( la)? (modalità chiara|tema chiaro)|disattiva( la)? modalità scura", c):
            return _local("sys", "dark", "off")
        if fm(r"(fai|scatta|cattura)( uno| una)? (screenshot|schermata)", c):
            return _local("sys", "screenshot")
        if fm(r"(quanto manca|timer attivi|a che punto è il timer)( al timer)?", c):
            return _local("timer", "list")
        if fm(r"(quali |che )?sveglie( ho| attive| impostate)?", c):
            return _local("alarm", "list")
        # sveglia: "metti una sveglia alle 7:30" / "sveglia alle 7"
        m = fm(r"(metti|imposta|punta)?( una)? ?sveglia (alle|per le|a) (\d{1,2})(?:[:.](\d{2}))?( di)?( domani)?( mattina)?", c)
        if m:
            h = int(m[4])
            mi = int(m[5]) if m[5] else 0
            if h < 24 and mi < 60:
                return _local("alarm", "set", f"{h:02d}:{mi:02d}")
        # app: solo se il nome e' di un'app davvero installata ("apri Chrome", "chiudi Spotify")
        m = fm(r"(apri|avvia|lancia) (l'app |l'applicazione |app )?((?:[^\W_]|[ .]){2,30})", c)
        if m:
            app = installed_app(m[3])
            if app:
                return _local("sys", "open", app)
        m = fm(r"(chiudi|esci da) (l'app |l'applicazione |app )?((?:[^\W_]|[ .]){2,30})", c)
        if m:
            app = installed_app(m[3])
            if app and "jarvis" not in app.lower():
                return _local("sys", "quit", app)
        return None


def installed_app(name: str) -> str | None:
    n = name.strip()
    if not n:
        return None
    try:
        from .tools.system import find_start_app
        hit = find_start_app(n, exact=True)
    except Exception:
        return None
    return hit[0] if hit else None
