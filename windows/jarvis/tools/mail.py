"""Mail (Gmail API) e Contatti (Google People API). Equivalente di Mail e Contatti su macOS."""
from __future__ import annotations

import base64
import mimetypes
import re
import webbrowser
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from .. import gate
from ..core import ActionLog, Args, Refs, ToolError, clip
from ..google_auth import call, service


def short_sender(s: str) -> str:
    """'Mario Rossi <mario@x.it>' -> 'Mario Rossi'"""
    i = s.find(" <")
    return s[:i].replace('"', "") if i >= 0 else s


def _hdr(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _walk_parts(payload: dict):
    yield payload
    for p in payload.get("parts", []) or []:
        yield from _walk_parts(p)


def _body_text(payload: dict) -> str:
    plain, html = "", ""
    for p in _walk_parts(payload):
        data = (p.get("body") or {}).get("data")
        if not data or p.get("filename"):
            continue
        mt = p.get("mimeType", "")
        if mt == "text/plain" and not plain:
            plain = _b64(data).decode("utf-8", errors="replace")
        elif mt == "text/html" and not html:
            html = _b64(data).decode("utf-8", errors="replace")
    if plain:
        return plain
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    for k, v in {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}.items():
        text = text.replace(k, v)
    return re.sub(r"[ \t]+", " ", text)


def run_mail(a: list[str], confirmed: bool = False, raw: list[str] | None = None) -> str:
    return call(lambda: _run_mail(a, confirmed, raw or []))


def _run_mail(a: list[str], confirmed: bool, raw: list[str]) -> str:
    if not a:
        raise ToolError("uso: mail unread|search|read|draft|send")
    sub = a[0]
    args = Args(a[1:])
    svc = service("gmail", "v1")
    if sub in ("unread", "search"):
        pos = list(args.pos)
        n = 8
        if pos and pos[-1].isdigit() and (sub == "unread" or len(pos) > 1):
            n = int(pos.pop())
        q = " ".join(pos) if sub == "search" else ""
        if sub == "search" and not q:
            raise ToolError("uso: mail search <testo> [N]")
        n = min(n, 25)
        if sub == "unread":
            query = "in:inbox is:unread"
            total = svc.users().labels().get(userId="me", id="INBOX").execute().get("messagesUnread", 0)
        else:
            qq = q.replace('"', "")
            query = f'in:inbox (from:"{qq}" OR subject:"{qq}")'
        res = svc.users().messages().list(userId="me", q=query, maxResults=n).execute()
        ids = [m["id"] for m in res.get("messages", [])]
        if sub == "search":
            total = res.get("resultSizeEstimate", len(ids))
        if not ids:
            return "Nessuna mail non letta." if sub == "unread" else f'Nessuna mail trovata per "{q}".'
        rows = []
        for mid in ids:
            m = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                           metadataHeaders=["From", "Subject"]).execute()
            when = datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000)
            rows.append((mid, short_sender(_hdr(m, "From")), _hdr(m, "Subject"), when))
        refs = Refs.assign("m", [r[0] for r in rows])
        body = "\n".join(f"[{ref}] {r[3]:%Y-%m-%d %H:%M} {r[1]}: {r[2]}" for ref, r in zip(refs, rows))
        head = f"{total} non lette" if sub == "unread" else f"{total} risultati"
        if total > len(rows):
            head += f" (mostro {len(rows)})"
        return head + ":\n" + body
    if sub == "read":
        r = args.pos[0] if args.pos else ""
        mid = Refs.resolve(r) or (r if re.fullmatch(r"[0-9a-fA-F]{8,}", r) else None)
        if not mid:
            raise ToolError("uso: mail read <m1>")
        m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        svc.users().messages().modify(userId="me", id=mid, body={"removeLabelIds": ["UNREAD"]}).execute()
        atts = "; ".join(p["filename"] for p in _walk_parts(m.get("payload", {})) if p.get("filename"))
        content = re.sub(r"\n{3,}", "\n\n", _body_text(m.get("payload", {})).strip())
        content = content if len(content) <= 1800 else content[:1800] + " [...]"
        return f"Da: {_hdr(m, 'From')}\nOggetto: {_hdr(m, 'Subject')}" + (f"\nAllegati: {atts}" if atts else "") + f"\n\n{content}"
    if sub in ("draft", "send"):
        to = args.list("to")
        if not to:
            raise ToolError("manca --to (indirizzo email; usa `jarvis contact <nome>` se serve)")
        bad = next((t for t in to if "@" not in t), None)
        if bad:
            raise ToolError(f'"{bad}" non è un indirizzo email: usa prima `jarvis contact {bad}`')
        subject = args.o("subject", "oggetto") or ""
        body = (args.o("body", "testo") or "").replace("\\n", "\n")
        from .files import resolve_existing
        files = [resolve_existing(f) for f in args.list("attach", "allegato")]
        names = [Path(f).name for f in files]
        att_text = "" if not files else f" con allegat{'o' if len(files) == 1 else 'i'} {', '.join(names)}"
        if sub == "send" and not confirmed:
            preview = clip(body, 160)
            return gate.request(f'Inviare mail a {", ".join(to)}, oggetto "{subject}"{att_text}, testo: "{preview}"', raw)
        msg = EmailMessage()
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(body)
        for f in files:
            ctype, _ = mimetypes.guess_type(f)
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            msg.add_attachment(Path(f).read_bytes(), maintype=maintype, subtype=subtype, filename=Path(f).name)
        enc = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        if sub == "send":
            svc.users().messages().send(userId="me", body={"raw": enc}).execute()
        else:
            svc.users().drafts().create(userId="me", body={"message": {"raw": enc}}).execute()
            webbrowser.open("https://mail.google.com/mail/u/0/#drafts")
        what = "Inviata mail" if sub == "send" else "Bozza pronta in Gmail"
        ActionLog.add("MAIL_PROTOCOL", f"{what} a {', '.join(to)}{att_text}")
        return f'{what} a {", ".join(to)}, oggetto "{subject}"{att_text}.'
    raise ToolError(f"sottocomando mail sconosciuto: {sub}")


def people_search(query: str, limit: int = 6) -> list[dict]:
    """Cerca nei contatti Google: lista di {name, emails, phones}."""
    svc = service("people", "v1")
    mask = "names,emailAddresses,phoneNumbers"
    # Google consiglia una richiesta vuota di "riscaldamento" prima della prima ricerca (cache lato server).
    try:
        svc.people().searchContacts(query="", readMask=mask, pageSize=1).execute()
    except Exception:
        pass
    res = svc.people().searchContacts(query=query, readMask=mask, pageSize=limit).execute()
    out = []
    for r in res.get("results", []):
        p = r.get("person", {})
        out.append({"name": (p.get("names") or [{}])[0].get("displayName", ""),
                    "emails": [e.get("value", "") for e in p.get("emailAddresses", [])],
                    "phones": [t.get("value", "") for t in p.get("phoneNumbers", [])]})
    return out


def run_contact(a: list[str]) -> str:
    q = " ".join(a)
    if not q:
        raise ToolError("uso: contact <nome>")
    rows = call(lambda: people_search(q))
    if not rows:
        return f'Nessun contatto trovato per "{q}".'
    return "\n".join(f"{r['name']}: {' '.join(r['emails']) if r['emails'] else '(nessuna email)'}" for r in rows)
