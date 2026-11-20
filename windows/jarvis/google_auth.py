"""Accesso agli account Google (Calendar, Tasks, Gmail, People).

Il login interattivo (`jarvis google login`) lo fa solo l'utente, dal terminale. Gli strumenti usano soltanto
il token gia' salvato (token rinnovato in automatico) e non aprono mai finestre di login.

File (in %APPDATA%\\JARVIS, mai nel repository):
  google_client.json : credenziali "App desktop" create nella Google Cloud Console (vedi README)
  google_token.json  : token dell'utente, creato dal login
"""
from __future__ import annotations

from .core import Paths, ToolError

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/contacts.readonly",
]
CLIENT_FILE = "google_client.json"
TOKEN_FILE = "google_token.json"

_NOT_LINKED = "account Google non collegato: nel terminale esegui `jarvis google login` (vedi README, sezione Windows)"


def credentials():
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        raise ToolError("librerie Google non installate: esegui `pip install -e .` nella cartella windows")
    path = Paths.file(TOKEN_FILE)
    if not path.exists():
        raise ToolError(_NOT_LINKED)
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if creds.refresh_token:
            try:
                creds.refresh(Request())
                path.write_text(creds.to_json(), encoding="utf-8")
            except RefreshError:
                raise ToolError("accesso Google scaduto o revocato: esegui di nuovo `jarvis google login`")
            except Exception as e:
                raise ToolError(f"impossibile rinnovare l'accesso Google ({type(e).__name__}): controlla la rete")
        else:
            raise ToolError(_NOT_LINKED)
    return creds


def service(name: str, version: str):
    """Un client per chiamata: i client di googleapiclient non sono thread-safe."""
    from googleapiclient.discovery import build
    return build(name, version, credentials=credentials(), cache_discovery=False)


def api_error(e: Exception) -> ToolError:
    """Traduce gli errori HTTP di Google in messaggi comprensibili."""
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return ToolError(str(e))
    if isinstance(e, HttpError):
        status = getattr(e.resp, "status", 0)
        if status in (401, 403):
            return ToolError("permesso negato da Google: abilita l'API nel progetto Cloud o rifai `jarvis google login` "
                             f"(dettaglio: {e._get_reason()})")
        if status == 404:
            return ToolError("elemento non trovato su Google (forse già modificato): rifai l'elenco")
        return ToolError(f"errore Google {status}: {e._get_reason()}")
    return ToolError(f"{type(e).__name__}: {e}")


def call(fn):
    """Esegue una funzione che usa l'API e converte gli errori in ToolError."""
    try:
        return fn()
    except ToolError:
        raise
    except Exception as e:
        raise api_error(e)
