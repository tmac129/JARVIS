"""Chiamate dirette alle API di Windows tramite ctypes (nessuna dipendenza esterna).

Si importa solo su Windows: gli altri moduli lo usano dentro funzioni, dopo aver controllato IS_WINDOWS.
"""
from __future__ import annotations

import ctypes
import time
import uuid
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:
    dwmapi = None

# Prototipi espliciti: senza, ctypes tratta i valori di ritorno come int a 32 bit.
_H = ctypes.c_void_p
user32.GetForegroundWindow.restype = _H
user32.IsWindowVisible.argtypes = [_H]
user32.GetWindow.argtypes = [_H, wintypes.UINT]
user32.GetWindow.restype = _H
user32.GetWindowLongW.argtypes = [_H, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [_H]
user32.GetWindowTextW.argtypes = [_H, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [_H, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindow.argtypes = [_H]
user32.GetWindowRect.argtypes = [_H, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowDC.argtypes = [_H]
user32.GetWindowDC.restype = _H
user32.ReleaseDC.argtypes = [_H, _H]
user32.PrintWindow.argtypes = [_H, _H, wintypes.UINT]
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
gdi32.CreateCompatibleDC.argtypes = [_H]
gdi32.CreateCompatibleDC.restype = _H
gdi32.CreateCompatibleBitmap.argtypes = [_H, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = _H
gdi32.SelectObject.argtypes = [_H, _H]
gdi32.SelectObject.restype = _H
gdi32.DeleteObject.argtypes = [_H]
gdi32.DeleteDC.argtypes = [_H]
gdi32.GetDIBits.argtypes = [_H, _H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
if dwmapi is not None:
    dwmapi.DwmGetWindowAttribute.argtypes = [_H, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


# ----------------------------------------------------------------------------- cartelle note

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, s: str):
        u = uuid.UUID(s)
        super().__init__(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


_FOLDER_IDS = {
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


def known_folder(name: str) -> str | None:
    fid = _FOLDER_IDS.get(name)
    if not fid:
        return None
    path = ctypes.c_wchar_p()
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
    if shell32.SHGetKnownFolderPath(ctypes.byref(_GUID(fid)), 0, None, ctypes.byref(path)) != 0:
        return None
    try:
        return path.value
    finally:
        ole32.CoTaskMemFree(path)


# ----------------------------------------------------------------------------- finestre

WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9


def window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _is_cloaked(hwnd: int) -> bool:
    if dwmapi is None:
        return False
    v = wintypes.DWORD()
    return dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v)) == 0 and v.value != 0


def visible_windows() -> list[tuple[int, str, int]]:
    """Finestre di primo livello visibili e con titolo: (hwnd, titolo, pid)."""
    out: list[tuple[int, str, int]] = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):   # GW_OWNER: salta le finestre figlie
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW or _is_cloaked(hwnd):
            return True
        title = window_title(hwnd)
        if title:
            out.append((hwnd, title, window_pid(hwnd)))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def foreground_window() -> tuple[int, str, int] | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    return hwnd, window_title(hwnd), window_pid(hwnd)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    if dwmapi is not None and dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) == 0:
        return r.left, r.top, r.right, r.bottom
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


# ----------------------------------------------------------------------------- cattura di una finestra (anche se coperta)

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def capture_window(hwnd: int):
    """Immagine PIL della finestra, ottenuta con PrintWindow: funziona anche se e' coperta dal HUD.
    Restituisce None se la cattura non riesce (finestra minimizzata, protetta, ecc.)."""
    from PIL import Image
    l, t, r, b = window_rect(hwnd)
    w, h = r - l, b - t
    if w < 50 or h < 50:
        return None
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        # PW_RENDERFULLCONTENT (2): include anche il contenuto delle finestre con accelerazione hardware
        if not user32.PrintWindow(hwnd, mem, 2):
            return None
        gdi32.SelectObject(mem, old)      # GetDIBits vuole la bitmap non selezionata in un contesto
        old = None
        bi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0):
            return None
        img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        if img.getextrema() == ((0, 0), (0, 0), (0, 0)):   # tutta nera: la cattura non ha funzionato
            return None
        return img
    finally:
        if old is not None:
            gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


# ----------------------------------------------------------------------------- tasti multimediali, blocco, sospensione

VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK, VK_MEDIA_PLAY_PAUSE = 0xB0, 0xB1, 0xB3
KEYEVENTF_KEYUP = 0x0002


def press_media_key(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def lock_workstation() -> bool:
    return bool(user32.LockWorkStation())


def suspend() -> None:
    """Sospensione (non ibernazione), anche se l'ibernazione e' attiva."""
    ctypes.WinDLL("powrprof").SetSuspendState(False, True, False)


def broadcast_theme_change() -> None:
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet", SMTO_ABORTIFHUNG, 5000, None)


# ----------------------------------------------------------------------------- tema

def set_dark_mode(dark: bool | None) -> bool:
    """Imposta (o inverte, se None) il tema scuro di app e sistema. Restituisce lo stato finale."""
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        if dark is None:
            cur, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            dark = bool(cur)   # era chiaro -> diventa scuro
        v = 0 if dark else 1
        winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD, v)
        winreg.SetValueEx(k, "SystemUsesLightTheme", 0, winreg.REG_DWORD, v)
    broadcast_theme_change()
    return dark
