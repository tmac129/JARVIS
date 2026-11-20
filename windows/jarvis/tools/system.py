"""Comandi di sistema: app, volume, luminosita', Wi-Fi, tema, blocco, sospensione, screenshot, batteria."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..core import IS_WINDOWS, ActionLog, Paths, Store, ToolError, fold, powershell, run_process, spawn_detached

# ----------------------------------------------------------------------------- app installate (Menu Start)

_APPS_TTL = 6 * 3600


def _scan_lnk() -> list[tuple[str, str]]:
    out = []
    roots = [os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs"),
             os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")]
    for root in roots:
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                if fn.lower().endswith(".lnk"):
                    out.append((fn[:-4], os.path.join(dp, fn)))
    return out


def start_apps(refresh: bool = False) -> list[tuple[str, str]]:
    """(nome, AppID) di tutte le app del Menu Start, comprese quelle dello Store. Cache di 6 ore."""
    cache = Store.load("startapps.json", {}) or {}
    if not refresh and cache.get("apps") and time.time() - cache.get("ts", 0) < _APPS_TTL:
        return [tuple(x) for x in cache["apps"]]
    apps: list[tuple[str, str]] = []
    if IS_WINDOWS:
        try:
            r = powershell("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress", timeout=30)
            data = json.loads(r.out) if r.out else []
            if isinstance(data, dict):
                data = [data]
            apps = [(d["Name"], d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]
        except (ToolError, ValueError, KeyError):
            apps = []
        if not apps:
            apps = _scan_lnk()
        Store.save("startapps.json", {"ts": time.time(), "apps": apps})
    return apps


def find_start_app(name: str, exact: bool = False) -> tuple[str, str] | None:
    n = fold(name.strip())
    if not n:
        return None
    apps = start_apps()
    for a in apps:
        if fold(a[0]) == n:
            return a
    if exact:
        return None
    starts = [a for a in apps if fold(a[0]).startswith(n)]
    if starts:
        return min(starts, key=lambda a: len(a[0]))
    part = [a for a in apps if n in fold(a[0])]
    return min(part, key=lambda a: len(a[0])) if part else None


def _launch(app: tuple[str, str]) -> None:
    name, appid = app
    if appid.lower().endswith(".lnk") and os.path.exists(appid):
        os.startfile(appid)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"])


# ----------------------------------------------------------------------------- finestre e processi

def _process_name(pid: int) -> str:
    import psutil
    try:
        return Path(psutil.Process(pid).name()).stem
    except psutil.Error:
        return ""


def open_windows() -> list[tuple[str, str, int]]:
    """(nome app, titolo, pid) delle finestre visibili, senza JARVIS stesso."""
    if not IS_WINDOWS:
        return []
    from .. import winapi
    me = os.getpid()
    out = []
    for _hwnd, title, pid in winapi.visible_windows():
        if pid == me or "j.a.r.v.i.s" in title.lower():
            continue
        name = _process_name(pid)
        if name.lower() == "applicationframehost":   # app UWP: il nome vero e' nel titolo della finestra
            name = title
        if name:
            out.append((name, title, pid))
    return out


def _quit_app(arg: str) -> str:
    wins = open_windows()
    n = fold(arg)
    hit = next((w for w in wins if fold(w[0]) == n), None) or next((w for w in wins if n in fold(w[0]) or n in fold(w[1])), None)
    if not hit:
        return f"{arg} non è aperta."
    name, _title, pid = hit
    if "jarvis" in name.lower():
        raise ToolError("non posso chiudere me stesso da qui: usa il menu nella barra delle applicazioni")
    # senza /F taskkill chiede la chiusura alle finestre, come terminate() sul Mac: l'app puo' chiedere di salvare
    run_process(["taskkill.exe", "/PID", str(pid)], timeout=15)
    ActionLog.add("SYSTEM", f"Chiusa {name}")
    return f"Chiusa {name}."


# ----------------------------------------------------------------------------- volume e luminosita'

def _endpoint_volume():
    try:
        import comtypes
        comtypes.CoInitialize()      # i comandi locali girano anche in thread di lavoro del HUD
    except Exception:
        pass
    from pycaw.pycaw import AudioUtilities
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):
        return dev.EndpointVolume
    import comtypes
    from ctypes import POINTER, cast
    from pycaw.pycaw import IAudioEndpointVolume
    return cast(dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))


def volume(v: str) -> str:
    if not IS_WINDOWS:
        raise ToolError("il volume si regola solo su Windows")
    try:
        ep = _endpoint_volume()
        cur = round(ep.GetMasterVolumeLevelScalar() * 100)
        if v in ("su", "+", "alza", "up"):
            cur = min(100, cur + 12)
            ep.SetMute(0, None)
            ep.SetMasterVolumeLevelScalar(cur / 100, None)
        elif v in ("giu", "giù", "-", "abbassa", "down"):
            cur = max(0, cur - 12)
            ep.SetMasterVolumeLevelScalar(cur / 100, None)
        elif v in ("muto", "mute", "off"):
            ep.SetMute(1, None)
        elif v in ("attiva", "unmute", "on"):
            ep.SetMute(0, None)
        elif v != "":
            digits = re.sub(r"\D", "", v)
            if not digits:
                raise ToolError("uso: sys volume 0-100|su|giu|muto|attiva")
            cur = min(max(int(digits), 0), 100)
            ep.SetMasterVolumeLevelScalar(cur / 100, None)
        muted = bool(ep.GetMute())
        cur = round(ep.GetMasterVolumeLevelScalar() * 100)
    except ToolError:
        raise
    except ImportError:
        raise ToolError("libreria pycaw mancante: esegui `pip install -e .` nella cartella windows")
    except Exception as e:
        raise ToolError(f"audio non raggiungibile ({type(e).__name__})")
    if v != "":
        ActionLog.add("SYSTEM", f"Volume {cur}%")
    return "Audio disattivato." if muted else f"Volume al {cur}%."


def brightness(v: str) -> str:
    try:
        import screen_brightness_control as sbc
    except ImportError:
        raise ToolError("libreria screen-brightness-control mancante: esegui `pip install -e .`")
    try:
        cur = sbc.get_brightness()
        cur = int(next((x for x in cur if x is not None), 50))
        if v in ("su", "+", "alza", "up"):
            target = min(100, cur + 12)
        elif v in ("giu", "giù", "-", "abbassa", "down"):
            target = max(0, cur - 12)
        else:
            digits = re.sub(r"\D", "", v)
            if not digits:
                raise ToolError("uso: sys brightness 0-100|su|giu")
            target = min(max(int(digits), 0), 100)
        sbc.set_brightness(target)
    except ToolError:
        raise
    except Exception:
        raise ToolError("luminosità non regolabile su questo schermo (serve uno schermo integrato o un monitor con DDC/CI)")
    ActionLog.add("SYSTEM", "Luminosità regolata")
    return "Luminosità regolata."


_WIFI_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($WinRtTask, $ResultType) { $asTask = $asTaskGeneric.MakeGenericMethod($ResultType); $netTask = $asTask.Invoke($null, @($WinRtTask)); $netTask.Wait(-1) | Out-Null; $netTask.Result }
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$wifi = $radios | Where-Object { $_.Kind -eq 'WiFi' }
if (-not $wifi) { Write-Output 'NOWIFI'; exit 2 }
$r = Await ($wifi.SetStateAsync($env:JARVIS_WIFI_STATE)) ([Windows.Devices.Radios.RadioAccessStatus])
Write-Output $r
"""


def wifi(on: bool) -> str:
    env = dict(os.environ, JARVIS_WIFI_STATE="On" if on else "Off")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" + _WIFI_SCRIPT],
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    out = r.stdout.strip()
    if "NOWIFI" in out:
        raise ToolError("nessuna scheda Wi-Fi trovata su questo PC")
    if "Allowed" not in out:
        raise ToolError("Windows non permette di cambiare il Wi-Fi da qui: usa il pannello rapido (Win+A)")
    ActionLog.add("SYSTEM", f"Wi-Fi {'attivato' if on else 'disattivato'}")
    return f"Wi-Fi {'attivato' if on else 'disattivato'}."


# ----------------------------------------------------------------------------- comando principale

def looks_like_path(arg: str) -> bool:
    """Percorso, indirizzo o protocollo (C:\\..., .\\x.exe, \\\\server\\share, https://, ms-...:) invece del nome di un'app."""
    return any(ch in arg for ch in "/\\:%~") or arg.startswith(".")


def run(a: list[str], confirmed: bool = False, raw: list[str] | None = None) -> str:
    sub = a[0] if a else ""
    arg = " ".join(a[1:]).strip()
    if sub in ("open", "apri"):
        if not arg:
            raise ToolError("uso: sys open <app>")
        # Un percorso o un protocollo aprirebbe qualsiasi file (anche un .exe o uno script scaricato):
        # sempre con conferma, come `file open`. I nomi delle app installate restano immediati.
        path_like = looks_like_path(arg)
        if path_like and not confirmed:
            from .. import gate
            return gate.request(f"Aprire {arg} (percorso o indirizzo, non un'app installata)", raw or ["sys", *a])
        if not IS_WINDOWS:
            raise ToolError("l'apertura delle app richiede Windows")
        if path_like:
            try:
                os.startfile(arg)  # type: ignore[attr-defined]
            except OSError:
                raise ToolError(f'"{arg}" non trovato')
            ActionLog.add("SYSTEM", f"Aperto {arg}")
            return f"Aperto {arg}."
        app = find_start_app(arg)
        try:
            if app:
                _launch(app)
            else:
                os.startfile(arg)  # type: ignore[attr-defined]   # nome di un programma nel PATH o in App Paths
        except OSError:
            raise ToolError(f'app "{arg}" non trovata')
        ActionLog.add("SYSTEM", f"Aperta {app[0] if app else arg}")
        return f"Aperta {app[0] if app else arg}."
    if sub in ("quit", "chiudi"):
        if not arg:
            raise ToolError("uso: sys quit <app>")
        return _quit_app(arg)
    if sub == "apps":
        names = []
        for name, _t, _p in open_windows():
            if name not in names:
                names.append(name)
        return "App aperte: " + ", ".join(names)
    if sub == "volume":
        return volume(arg.lower())
    if sub in ("brightness", "luminosita", "luminosità"):
        return brightness(arg.lower())
    if sub == "wifi":
        return wifi(arg.lower() in ("on", "acceso", "accendi", "attiva", "1"))
    if sub in ("dark", "scuro"):
        if not IS_WINDOWS:
            raise ToolError("il tema si cambia solo su Windows")
        from .. import winapi
        want = {"on": True, "attiva": True, "si": True, "sì": True, "off": False, "disattiva": False, "no": False}.get(arg.lower())
        dark = winapi.set_dark_mode(want)
        ActionLog.add("SYSTEM", f"Modalità scura {'attiva' if dark else 'disattiva'}")
        return f"Modalità scura {'attivata' if dark else 'disattivata'}."
    if sub in ("lock", "blocca"):
        if not IS_WINDOWS:
            raise ToolError("il blocco dello schermo richiede Windows")
        from .. import winapi
        winapi.lock_workstation()
        ActionLog.add("SYSTEM", "Schermo bloccato")
        return "Schermo bloccato."
    if sub in ("sleep", "stop"):
        if not IS_WINDOWS:
            raise ToolError("la sospensione richiede Windows")
        spawn_detached([sys.executable, "-c",
                        "import time,ctypes;time.sleep(4);ctypes.WinDLL('powrprof').SetSuspendState(False,True,False)"])
        ActionLog.add("SYSTEM", "Sospensione del PC tra 4 secondi")
        return "Metto in sospensione il PC tra 4 secondi."
    if sub in ("screenshot", "schermata"):
        try:
            from PIL import ImageGrab
        except ImportError:
            raise ToolError("libreria Pillow mancante: esegui `pip install -e .`")
        path = Paths.known_folder("Desktop") / f"Schermata JARVIS {datetime.now():%Y-%m-%d alle %H.%M.%S}.png"
        ImageGrab.grab(all_screens=True).save(path)
        ActionLog.add("SYSTEM", "Screenshot salvato sulla Scrivania")
        return "Screenshot salvato sulla Scrivania."
    if sub in ("battery", "batteria"):
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "Batteria: nessuna batteria rilevata (PC fisso)."
        state = "in carica" if b.power_plugged and b.percent < 100 else ("carica" if b.power_plugged else "in scarica")
        s = f"Batteria: {round(b.percent)}%; {state}"
        if not b.power_plugged and b.secsleft not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED) and b.secsleft > 0:
            s += f"; {b.secsleft // 3600}:{(b.secsleft % 3600) // 60:02d} rimanenti"
        return s
    raise ToolError("uso: sys open|quit|apps|volume|brightness|wifi|dark|lock|sleep|screenshot|battery")
