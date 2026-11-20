"""Voce: riconoscimento italiano offline (Vosk, push-to-talk o parola "Jarvis") e sintesi (SAPI).

Il riconoscimento avviene sul PC: l'audio non esce mai dalla macchina.
Il modello italiano si scarica una volta sola con `jarvis setup-voice`.
"""
from __future__ import annotations

import json
import math
import os
import queue
import random
import re
import struct
import threading
import time
from pathlib import Path

WAKE_WORDS = ["jarvis", "jarvi", "giarvis", "gervis", "jervis", "jarvys", "charvis", "jarbis"]
SAMPLE_RATE = 16000


# ----------------------------------------------------------------------------- modello Vosk

def model_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("VOSK_MODEL_PATH"):
        dirs.append(Path(os.environ["VOSK_MODEL_PATH"]))
    dirs += [Path.home() / "AppData" / "Local" / "vosk", Path.home() / ".cache" / "vosk"]
    return dirs


def find_model() -> str | None:
    for d in model_dirs():
        if d.is_dir():
            for sub in sorted(d.iterdir()):
                if re.match(r"vosk-model(-small)?-it", sub.name) and sub.is_dir():
                    return str(sub)
    return None


def setup_model() -> int:
    """Scarica il modello italiano piccolo (circa 50 MB) con la funzione ufficiale della libreria Vosk."""
    try:
        from vosk import Model
    except ImportError:
        print("Libreria vosk mancante: esegui `pip install -e .` nella cartella windows.")
        return 1
    if find_model():
        print(f"Modello italiano già presente: {find_model()}")
        return 0
    print("Scarico il modello vocale italiano (una tantum, da alphacephei.com)...")
    try:
        Model(lang="it")
    except Exception as e:
        print(f"Download non riuscito: {e}")
        return 1
    print("Modello installato. Riavvia JARVIS per usare la voce.")
    return 0


def after_wake(text: str) -> str | None:
    """Testo dopo l'ultima parola di attivazione, o None se non e' stata pronunciata."""
    low = text.lower()
    best = None
    for w in WAKE_WORDS:
        i = low.rfind(w)
        if i >= 0 and (best is None or i > best[0]):
            best = (i, w)
    if best is None:
        return None
    return text[best[0] + len(best[1]):].strip(" ,.!?")


# ----------------------------------------------------------------------------- sintesi vocale (thread dedicato)

class SpeechThread:
    """SAPI e' COM: l'oggetto vive in un solo thread. Si parla e si interrompe tramite una coda."""

    def __init__(self, on_speaking, on_level):
        self.on_speaking = on_speaking
        self.on_level = on_level
        self._q: queue.Queue = queue.Queue()
        self._voice_id: str | None = None
        self._voices: list[tuple[str, str]] = []
        self._ready = threading.Event()
        self.speaking = False
        threading.Thread(target=self._run, daemon=True).start()

    def speak(self, text: str) -> None:
        self._q.put(("speak", text))

    def stop(self) -> None:
        self._q.put(("stop", None))

    def set_voice(self, voice_id: str | None) -> None:
        self._voice_id = voice_id
        self._q.put(("voice", voice_id))

    def voices(self) -> list[tuple[str, str]]:
        self._ready.wait(5)
        return list(self._voices)

    def _run(self) -> None:
        from ..speech import Speaker
        sp = Speaker()
        sp.set_voice(self._voice_id)
        try:
            self._voices = sp.voices()
        except Exception:
            self._voices = []
        self._ready.set()
        was = False
        while True:
            try:
                cmd, arg = self._q.get(timeout=0.1)
            except queue.Empty:
                cmd, arg = None, None
            try:
                if cmd == "speak":
                    sp.speak(arg)
                elif cmd == "stop":
                    sp.stop()
                elif cmd == "voice":
                    sp.set_voice(arg)
            except Exception:
                pass
            now = sp.is_speaking
            if now:
                self.on_level(random.uniform(0.35, 0.75))   # il nucleo pulsa mentre parla
            if now != was:
                was = now
                self.speaking = now
                if not now:
                    self.on_level(0)
                self.on_speaking(now)


# ----------------------------------------------------------------------------- riconoscimento vocale

class Listener:
    def __init__(self, speech: SpeechThread, on_level, on_partial, on_command, on_listening, on_wake, on_error):
        self.speech = speech
        self.on_level, self.on_partial, self.on_command = on_level, on_partial, on_command
        self.on_listening, self.on_wake, self.on_error = on_listening, on_wake, on_error
        self.capturing = False
        self.hotword = False
        self._model = None
        self._stream = None
        self._rec = None
        self._q: queue.Queue = queue.Queue(maxsize=200)
        self._finals: list[str] = []
        self._partial = ""
        self._command = ""
        self._last_change = time.time()
        self._capture_start = time.time()
        self._task_started = time.time()
        self._worker: threading.Thread | None = None
        self._lock = threading.RLock()

    # ---- ciclo di vita

    def _ensure(self) -> bool:
        if self._model is None:
            path = find_model()
            if not path:
                self.on_error("Manca il modello vocale italiano: nel terminale esegui `jarvis setup-voice`, poi riavvia JARVIS.")
                return False
            try:
                from vosk import KaldiRecognizer, Model
                import sounddevice  # noqa: F401
                self._model = Model(path)
                self._KaldiRecognizer = KaldiRecognizer
            except Exception as e:
                self.on_error(f"Voce non disponibile: {e}")
                return False
        if self._stream is None:
            try:
                import sounddevice as sd
                self._stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=2000, dtype="int16", channels=1,
                                                 callback=self._audio_cb)
                self._stream.start()
            except Exception as e:
                self._stream = None
                self.on_error(f"Microfono non disponibile: {e}")
                return False
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._loop, daemon=True)
            self._worker.start()
        return True

    def _stop_stream(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self.on_level(0)

    def _new_task(self) -> None:
        self._rec = self._KaldiRecognizer(self._model, SAMPLE_RATE)
        self._finals, self._partial, self._heard = [], "", ""
        self._task_started = time.time()

    # ---- comandi

    def listen_once(self) -> None:
        """Push-to-talk: un comando, finisce dopo una pausa."""
        self.speech.stop()
        with self._lock:
            if not self._ensure():
                return
            self._new_task()
            self._begin_capture("")

    def cancel_listening(self) -> None:
        with self._lock:
            self.capturing = False
            self.on_listening(False)
            if not self.hotword:
                self._stop_stream()
            elif self._model:
                self._new_task()

    def set_hotword(self, on: bool) -> None:
        with self._lock:
            self.hotword = on
            if on:
                if self._ensure():
                    self._new_task()
                else:
                    self.hotword = False
            elif not self.capturing:
                self._stop_stream()

    def _begin_capture(self, initial: str) -> None:
        self.capturing = True
        self._command = initial
        self._capture_start = self._last_change = time.time()
        self.on_listening(True)
        if initial:
            self.on_partial(initial)

    # ---- audio

    def _audio_cb(self, indata, frames, time_info, status) -> None:
        data = bytes(indata)
        try:
            self._q.put_nowait(data)
        except queue.Full:
            pass
        # livello 0..1 dal valore RMS del blocco (campioni a 16 bit)
        n = len(data) // 2
        if n and self.capturing:
            samples = struct.unpack(f"<{n}h", data)
            rms = math.sqrt(sum(s * s for s in samples[::4]) / max(n // 4, 1)) / 32768
            db = 20 * math.log10(max(rms, 1e-6))
            self.on_level(max(0.0, min(1.0, (db + 50) / 40)))

    def _loop(self) -> None:
        while True:
            try:
                data = self._q.get(timeout=0.2)
            except queue.Empty:
                data = None
            with self._lock:
                if self._stream is None and not self.capturing:
                    return
                if data is not None and self._rec is not None:
                    if self.speech.speaking and not self.capturing:
                        continue                 # non ascoltare la propria voce
                    self._feed(data)
                self._check()

    def _feed(self, data: bytes) -> None:
        rec = self._rec
        if rec.AcceptWaveform(data):
            t = (json.loads(rec.Result()).get("text") or "").strip()
            if t:
                self._finals.append(t)
            self._partial = ""
        else:
            self._partial = (json.loads(rec.PartialResult()).get("partial") or "").strip()
        full = " ".join(self._finals + ([self._partial] if self._partial else [])).strip()
        if not full or full == getattr(self, "_heard", ""):
            return
        self._heard = full
        self._last_change = time.time()
        if self.capturing:
            rest = after_wake(full)
            self._command = rest if rest is not None else (self._command if self.hotword else full)
            self.on_partial(self._command)
        elif self.hotword:
            rest = after_wake(full)
            if rest is not None:
                self.on_wake()
                self.speech.stop()
                self._begin_capture(rest)

    def _check(self) -> None:
        now = time.time()
        if self.capturing:
            silence = now - self._last_change
            cmd = self._command.strip()
            if (cmd and silence > 1.4) or now - self._capture_start > 20:
                self.capturing = False
                self.on_listening(False)
                if cmd:
                    self.on_command(cmd)
                if self.hotword:
                    self._new_task()
                else:
                    self._stop_stream()
            elif not cmd and silence > 6:
                self.cancel_listening()
        elif self.hotword and now - self._task_started > 50:
            self._new_task()        # evita che la trascrizione cresca all'infinito
