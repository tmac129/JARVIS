"""`jarvis google login|status|logout`: collegamento dell'account Google (solo l'utente, mai il modello)."""
from __future__ import annotations

import os

from ..core import Paths, ToolError
from ..google_auth import CLIENT_FILE, SCOPES, TOKEN_FILE


def run(a: list[str]) -> str:
    sub = a[0] if a else "status"
    token = Paths.file(TOKEN_FILE)
    if sub in ("login", "logout") and os.environ.get("JARVIS_AGENT"):
        raise ToolError("il collegamento dell'account Google lo fa solo l'utente dal terminale")
    if sub == "status":
        if not Paths.file(CLIENT_FILE).exists():
            return f"Google: credenziali mancanti. Copia il file scaricato dalla Cloud Console in {Paths.file(CLIENT_FILE)}"
        return "Google: account collegato." if token.exists() else "Google: account non collegato (jarvis google login)."
    if sub == "logout":
        token.unlink(missing_ok=True)
        return "Account Google scollegato da questo PC."
    if sub == "login":
        client = Paths.file(CLIENT_FILE)
        if not client.exists():
            raise ToolError(f"manca {client}: scarica le credenziali 'App desktop' dalla Google Cloud Console e salvale lì")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent",
                                      authorization_prompt_message="Apro il browser per collegare l'account Google...",
                                      success_message="J.A.R.V.I.S. collegato. Puoi chiudere questa pagina.")
        token.write_text(creds.to_json(), encoding="utf-8")
        return "Account Google collegato."
    raise ToolError("uso: google login|status|logout")
