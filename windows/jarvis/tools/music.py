"""Musica: qualsiasi player (Spotify, browser, Lettore multimediale, VLC...) tramite i controlli multimediali di Windows.

Comandi e brano corrente passano dai "System Media Transport Controls" di Windows, gli stessi del pannello
volume: funzionano con ogni app che li espone. Se non sono disponibili si usano i tasti multimediali.
`music play <testo>` apre la ricerca di Spotify (nessun player permette di avviare un brano per nome dall'esterno).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse

from ..core import IS_WINDOWS, ActionLog, Args, ToolError

# Lo script non contiene mai dati dell'utente: l'azione arriva da una variabile d'ambiente fissa.
_SMTC_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($WinRtTask, $ResultType) { $asTask = $asTaskGeneric.MakeGenericMethod($ResultType); $netTask = $asTask.Invoke($null, @($WinRtTask)); $netTask.Wait(-1) | Out-Null; $netTask.Result }
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties,Windows.Media.Control,ContentType=WindowsRuntime] | Out-Null
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$s = $mgr.GetCurrentSession()
if (-not $s) { Write-Output 'NOSESSION'; exit 0 }
switch ($env:JARVIS_MEDIA_ACTION) {
  'play'  { Await ($s.TryPlayAsync()) ([bool]) | Out-Null }
  'pause' { Await ($s.TryPauseAsync()) ([bool]) | Out-Null }
  'next'  { Await ($s.TrySkipNextAsync()) ([bool]) | Out-Null; Start-Sleep -Milliseconds 700 }
  'prev'  { Await ($s.TrySkipPreviousAsync()) ([bool]) | Out-Null; Start-Sleep -Milliseconds 700 }
}
$p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
$st = [string]$s.GetPlaybackInfo().PlaybackStatus
[pscustomobject]@{ app = $s.SourceAppUserModelId; title = $p.Title; artist = $p.Artist; status = $st } | ConvertTo-Json -Compress
"""

_APP_NAMES = {
    "spotify": "Spotify", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "opera": "Opera",
    "brave": "Brave", "vlc": "VLC", "zunemusic": "Lettore multimediale", "zunevideo": "Film e TV",
    "applemusic": "Apple Music", "itunes": "iTunes", "deezer": "Deezer", "tidal": "Tidal", "amazonmusic": "Amazon Music",
    "youtubemusic": "YouTube Music", "308046b0af4a39cb": "Firefox",
}

_NO_PLAYER = "Nessun player multimediale aperto: avvia Spotify, un video nel browser o un altro player."


def app_name(aumid: str) -> str:
    """'Spotify.exe' -> 'Spotify', 'Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic' -> 'Lettore multimediale'."""
    s = (aumid or "").split("!")[-1].split("\\")[-1]
    if s.lower().endswith(".exe"):
        s = s[:-4]
    s = s.split(".")[-1] if "." in s else s
    return _APP_NAMES.get(s.lower().replace(" ", ""), s or "player")


def describe(info: dict) -> str:
    """Testo breve del brano: 'Artista - Titolo' (o solo il titolo)."""
    title, artist = (info.get("title") or "").strip(), (info.get("artist") or "").strip()
    return f"{artist} - {title}" if artist and title else title


def _smtc(action: str = "now") -> dict | None:
    """Esegue l'azione sul player attivo e ne restituisce lo stato. {} = nessun player; None = SMTC non disponibile."""
    env = dict(os.environ, JARVIS_MEDIA_ACTION=action)
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" + _SMTC_SCRIPT],
                           env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.strip()
    if "NOSESSION" in out:
        return {}
    try:
        line = [ln for ln in out.splitlines() if ln.startswith("{")][-1]
        return json.loads(line)
    except (IndexError, ValueError):
        return None


def _key(vk_name: str) -> None:
    from .. import winapi
    winapi.press_media_key(getattr(winapi, vk_name))


def _start_spotify() -> bool:
    """Apre Spotify se e' installato (serve quando nessun player e' aperto)."""
    try:
        os.startfile("spotify:")  # type: ignore[attr-defined]
    except OSError:
        return False
    for _ in range(8):
        time.sleep(1.0)
        if _smtc("now"):
            break
    return True


def run(a: list[str]) -> str:
    if not IS_WINDOWS:
        raise ToolError("il controllo della musica richiede Windows")
    args = Args(a)
    sub = args.pos[0] if args.pos else "now"
    query = " ".join(args.pos[1:])
    if sub in ("play", "riproduci", "metti"):
        if query:
            try:
                os.startfile("spotify:search:" + urllib.parse.quote(query))  # type: ignore[attr-defined]
            except OSError:
                raise ToolError("per cercare un brano per nome serve Spotify installato")
            return f'Nessun player permette di avviare un brano per nome: ho aperto la ricerca di "{query}" su Spotify.'
        info = _smtc("play")
        if info == {}:
            if not _start_spotify():
                return _NO_PLAYER
            info = _smtc("play")
        if info is None:
            _key("VK_MEDIA_PLAY_PAUSE")
            ActionLog.add("MUSIC", "Play (tasto multimediale)")
            return "Fatto."
        if not info:
            return _NO_PLAYER
        app = app_name(info.get("app", ""))
        ActionLog.add("MUSIC", f"Riproduzione su {app}")
        return f"Riproduzione avviata su {app}."
    if sub in ("pause", "pausa", "stop"):
        info = _smtc("pause")
        if info is None:
            _key("VK_MEDIA_PLAY_PAUSE")
        elif not info:
            return "Non c'è nulla in riproduzione."
        ActionLog.add("MUSIC", "Pausa")
        return "Musica in pausa."
    if sub == "toggle":
        _key("VK_MEDIA_PLAY_PAUSE")
        return "Fatto."
    if sub in ("next", "avanti", "successivo", "prev", "indietro", "precedente"):
        forward = sub in ("next", "avanti", "successivo")
        info = _smtc("next" if forward else "prev")
        if info is None:
            _key("VK_MEDIA_NEXT_TRACK" if forward else "VK_MEDIA_PREV_TRACK")
        elif not info:
            return _NO_PLAYER
        n = describe(info or {})
        if n:
            return f"Ora: {n}."
        return "Brano successivo." if forward else "Brano precedente."
    if sub in ("now", "cosa", "brano"):
        info = _smtc("now")
        if info is None:
            raise ToolError("Windows non espone il brano corrente su questo PC")
        n = describe(info)
        if not info or not n:
            return "Nessun brano in riproduzione."
        app = app_name(info.get("app", ""))
        state = "in pausa" if info.get("status") == "Paused" else "in riproduzione"
        return f"{n}, {state} su {app}."
    raise ToolError("uso: music play [testo]|pause|next|prev|now")
