@echo off
rem Installa JARVIS per Windows in un ambiente virtuale (.venv) dentro questa cartella.
rem Eseguilo da Prompt dei comandi, dentro la cartella "windows" del repository.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python non trovato. Installa Python 3.12 da python.org e spunta "Add python.exe to PATH".
  exit /b 1
)
py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv
if errorlevel 1 (
  echo Impossibile creare l'ambiente virtuale.
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo Installazione delle dipendenze non riuscita.
  exit /b 1
)
echo.
echo Fatto. Per usare JARVIS:
echo   1. .venv\Scripts\activate
echo   2. jarvis google login      (collega l'account Google, vedi README)
echo   3. jarvis-hud               (avvia l'interfaccia)
endlocal
