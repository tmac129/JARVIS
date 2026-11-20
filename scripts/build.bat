@echo off
rem JARVIS is a native macOS app (AppKit, EventKit, AppleScript, launchd, WebKit):
rem it cannot be built or run on Windows. This script only explains it instead of failing obscurely.
echo.
echo  JARVIS richiede macOS 14 o successivo (consigliato Apple Silicon).
echo  Su Windows non si puo' compilare ne' eseguire: usa le API native di macOS
echo  (Calendario, Promemoria, Mail, Note, Finder, launchd).
echo.
echo  Dal telefono o da un PC Windows puoi pero' usare la pagina web di JARVIS
echo  (menu JARVIS sul Mac ^> "Collega iPhone"), sulla stessa rete o via Tailscale.
echo.
exit /b 1
