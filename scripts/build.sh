#!/bin/zsh
# Builds JARVIS.app (HUD + jarvis CLI) into /Applications and links the CLI into ~/.local/bin.
# macOS only (AppKit, EventKit, AppleScript, launchd): on Windows use scripts\build.bat for an explanation.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "JARVIS richiede macOS 14 o successivo." >&2
  exit 1
fi
if ! command -v swift >/dev/null 2>&1; then
  echo "Swift non trovato: installa Xcode o i Command Line Tools (xcode-select --install)." >&2
  exit 1
fi

swift build -c release
APP="/Applications/JARVIS.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$HOME/.local/bin"
cp .build/release/JarvisHUD "$APP/Contents/MacOS/JarvisHUD"
cp .build/release/jarvis "$APP/Contents/MacOS/jarvis"
cp Resources/Info.plist "$APP/Contents/Info.plist"
cp -R HUD "$APP/Contents/Resources/HUD"
[[ -f Resources/AppIcon.icns ]] && cp Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

# Sign with an Apple Development certificate if present: a stable identity keeps macOS privacy
# permissions (Full Disk Access, Accessibility, Screen Recording) across rebuilds. Fallback: ad-hoc.
IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | grep "Apple Development" | head -1 | awk '{print $2}' || true)
codesign --force --deep --sign "${IDENTITY:--}" "$APP"
ln -sf "$APP/Contents/MacOS/jarvis" "$HOME/.local/bin/jarvis"
echo "JARVIS.app installata in $APP"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Nota: aggiungi ~/.local/bin al PATH per usare il comando 'jarvis' dal Terminale." ;;
esac
