"""Voce in uscita (SAPI di Windows tramite pywin32) e suoni."""
from __future__ import annotations

import re
import threading

from .core import IS_WINDOWS

_ITALIAN_LCID = "410"


def clean_for_speech(text: str) -> str:
    t = re.sub(r"\[[a-z]{1,2}\d+\]", "", text)
    return t.replace("*", "").replace("#", "").replace("J.A.R.V.I.S.", "Jarvis")


class Speaker:
    """Sintesi vocale non bloccante e interrompibile. Una istanza per processo, usata da un solo thread."""

    def __init__(self):
        self._voice = None
        self._voice_id: str | None = None
        self._lock = threading.Lock()

    def _sapi(self):
        if self._voice is None:
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
            import win32com.client  # type: ignore
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            self._select(self._voice_id)
            self._voice.Rate = 1
        return self._voice

    def voices(self) -> list[tuple[str, str]]:
        """(id, nome) delle voci italiane installate; se non ce ne sono, tutte."""
        all_v = [(t.Id, t.GetDescription(), t.GetAttribute("Language") or "") for t in self._tokens()]
        it = [(i, d) for i, d, lang in all_v if _ITALIAN_LCID in lang.split(";")]
        return it or [(i, d) for i, d, _ in all_v]

    def _select(self, voice_id: str | None) -> None:
        v = self._voice
        if v is None:
            return
        toks = self._tokens()
        for tok in toks:
            if voice_id and tok.Id == voice_id:
                v.Voice = tok
                return
        if not voice_id:   # nessuna scelta: la prima voce italiana
            for tok in toks:
                if _ITALIAN_LCID in (tok.GetAttribute("Language") or "").split(";"):
                    v.Voice = tok
                    return

    def _tokens(self) -> list:
        """Voci SAPI classiche piu' le voci "OneCore" scaricate da Impostazioni > Ora e lingua > Voce
        (es. Cosimo), che SAPI non elenca da solo. Doppioni (stesso nome) tolti."""
        v = self._sapi() if self._voice is None else self._voice
        toks, seen = [], set()
        items = v.GetVoices()
        for i in range(items.Count):
            toks.append(items.Item(i))
        try:
            import win32com.client  # type: ignore
            cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
            cat.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", False)
            extra = cat.EnumerateTokens()
            for i in range(extra.Count):
                toks.append(extra.Item(i))
        except Exception:
            pass
        out = []
        for t in toks:
            d = t.GetDescription()
            if d not in seen:
                seen.add(d)
                out.append(t)
        return out

    def set_voice(self, voice_id: str | None) -> None:
        self._voice_id = voice_id
        if self._voice is not None:
            self._select(voice_id)

    def speak(self, text: str, wait: bool = False) -> None:
        clean = clean_for_speech(text).strip()
        if not clean or not IS_WINDOWS:
            return
        with self._lock:
            v = self._sapi()
            # flag: 1 = asincrono, 2 = interrompi quanto sta parlando
            v.Speak(clean, 0 if wait else 3)

    def stop(self) -> None:
        if self._voice is not None and IS_WINDOWS:
            try:
                self._voice.Speak("", 3)
            except Exception:
                pass

    @property
    def is_speaking(self) -> bool:
        if self._voice is None:
            return False
        try:
            return self._voice.Status.RunningState == 2   # SRSEIsSpeaking
        except Exception:
            return False


def beep(times: int = 3) -> None:
    if not IS_WINDOWS:
        return
    import winsound
    for _ in range(times):
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)


def say_blocking(text: str) -> None:
    """Per processi brevi (sveglie e timer lanciati da Utilita' di pianificazione)."""
    try:
        Speaker().speak(text, wait=True)
    except Exception:
        pass
