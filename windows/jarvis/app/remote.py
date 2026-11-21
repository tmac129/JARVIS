"""Piccolo server HTTP sulla rete locale per usare JARVIS dal telefono.

  GET  /?token=...   web app mobile (da aggiungere alla schermata Home)
  GET  /ping         controllo del collegamento (con token)
  GET  /apple-touch-icon.png   icona per la schermata Home (senza token: non contiene dati)
  POST /ask          corpo: testo oppure {"text": "..."}; header "Authorization: Bearer <token>" oppure ?token=
Stesso cervello e stessa conferma delle azioni critiche. Spento finche' non lo attivi dal menu.
ATTENZIONE: e' HTTP in chiaro: usalo solo su una rete di cui ti fidi (o tramite Tailscale).
"""
from __future__ import annotations

import hmac
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..core import Store

PORT = 8787
MAX_BODY = 1_000_000
IDLE_TIMEOUT = 300          # nessuna connessione resta aperta per sempre


def get_token() -> str:
    cfg = Store.load("remote.json", {}) or {}
    if not cfg.get("token"):
        cfg = {"token": secrets.token_urlsafe(18)}
        Store.save("remote.json", cfg)
    return cfg["token"]


def local_addresses() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # nessun pacchetto parte: serve solo a scoprire l'interfaccia in uso
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254")) and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [i for i in ips if not i.startswith(("127.", "169.254"))]


def same_token(a: str | None, b: str) -> bool:
    """Confronto a tempo costante: il controllo del token non deve rivelare quanti caratteri coincidono."""
    return a is not None and hmac.compare_digest(a.encode(), b.encode())


class RemoteServer:
    def __init__(self, page_html, handler, icon_png=None):
        """page_html() -> str; handler(text, as_json, reply_callback); icon_png() -> bytes (facoltativo)."""
        self._icon = icon_png
        self._icon_cache: bytes | None = None
        self.token = get_token()
        self._page = page_html
        self._handler = handler
        self._httpd: ThreadingHTTPServer | None = None

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    def icon_png(self) -> bytes:
        if self._icon_cache is None:
            try:
                self._icon_cache = self._icon() if self._icon else b""
            except Exception:
                self._icon_cache = b""
        return self._icon_cache

    def url(self, host: str) -> str:
        return f"http://{host}:{PORT}/?token={self.token}"

    def start(self) -> None:
        if self._httpd:
            return
        server = self

        class H(BaseHTTPRequestHandler):
            timeout = IDLE_TIMEOUT
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):      # niente log in console
                pass

            def _send(self, code: int, ctype: str, body: str | bytes) -> None:
                b = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b)

            def _auth(self, query: dict) -> bool:
                auth = (query.get("token") or [None])[0]
                if auth is None:
                    hdr = self.headers.get("Authorization", "")
                    auth = hdr.replace("Bearer ", "", 1) if hdr else None
                return same_token(auth, server.token)

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                # icona della schermata Home: Safari la chiede senza token e non contiene nulla di privato
                if u.path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
                    png = server.icon_png()
                    return self._send(200, "image/png", png) if png else self._send(404, "text/plain", "Non trovato.")
                if not self._auth(q):
                    return self._send(401, "text/plain", "Token mancante o errato.")
                if u.path == "/ping":
                    return self._send(200, "text/plain", "ok")
                if u.path == "/":
                    return self._send(200, "text/html; charset=utf-8", server._page().replace("__TOKEN__", server.token))
                self._send(404, "text/plain", "Non trovato.")

            def do_POST(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY:
                    return self._send(400, "text/plain", "Richiesta non valida.")
                body = self.rfile.read(length)
                if not self._auth(q):
                    return self._send(401, "text/plain", "Token mancante o errato.")
                if u.path not in ("/ask", "/ask.json"):
                    return self._send(404, "text/plain", "Non trovato.")
                text = body.decode("utf-8", errors="replace")
                try:
                    o = json.loads(body)
                    if isinstance(o, dict) and isinstance(o.get("text"), str):
                        text = o["text"]
                except ValueError:
                    pass
                text = text.strip()
                if not text:
                    return self._send(400, "text/plain", "Testo vuoto.")
                as_json = u.path.endswith(".json")
                done = threading.Event()
                box: dict = {}
                server._handler(text, as_json, lambda r: (box.update(r=r), done.set()))
                if not done.wait(IDLE_TIMEOUT):
                    return self._send(504, "text/plain", "Tempo scaduto.")
                self._send(200, "application/json" if as_json else "text/plain; charset=utf-8", box["r"])

        self._httpd = ThreadingHTTPServer(("0.0.0.0", PORT), H)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def qr_png(text: str, path) -> None:
    import qrcode
    qrcode.make(text).save(str(path))
