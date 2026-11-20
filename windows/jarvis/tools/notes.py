"""Note: file Markdown nella cartella Documenti\\JARVIS Note (non esiste un'app Note di Windows con API locale).

Ogni nota e' un file .md; `--folder F` e' una sottocartella. Le note si aprono e si modificano anche a mano.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core import ActionLog, Args, Paths, Refs, ToolError, fold


def notes_dir() -> Path:
    d = Paths.known_folder("Documents") / "JARVIS Note"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name).strip(" .")
    return re.sub(r"\s+", " ", s)[:80] or "Nota"


def _all_notes() -> list[Path]:
    root = notes_dir()
    return sorted(root.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def _title(p: Path) -> str:
    try:
        with open(p, encoding="utf-8") as f:
            first = f.readline().strip()
        return first.lstrip("# ").strip() or p.stem
    except OSError:
        return p.stem


def _resolve(ref: str | None) -> Path:
    rel = Refs.resolve(ref) if ref else None
    p = (notes_dir() / rel) if rel else None
    # la nota deve restare dentro la cartella delle note
    if not p or not p.resolve().is_relative_to(notes_dir().resolve()) or not p.exists():
        raise ToolError("nota non trovata: usa prima `note list` o `note search` e poi [ntN]")
    return p


def run(a: list[str]) -> str:
    sub = a[0] if a else "list"
    args = Args(a[1:])
    root = notes_dir()
    if sub in ("add", "nuova", "crea"):
        title = args.o("title", "titolo") or (" ".join(args.pos) if args.pos else None)
        if not title:
            raise ToolError("uso: note add --title T [--body testo] [--folder F]")
        folder = root
        if args.o("folder", "cartella"):
            folder = root / _safe(args.o("folder", "cartella"))
            folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_safe(title)}.md"
        i = 2
        while path.exists():
            path = folder / f"{_safe(title)} {i}.md"
            i += 1
        body = (args.o("body", "testo") or "").replace("\\n", "\n")
        path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        ActionLog.add("NOTES", f'Creata nota "{title}"')
        return f'Nota "{title}" creata.'
    if sub in ("list", "search", "cerca"):
        q = "" if sub == "list" else " ".join(args.pos)
        notes = _all_notes()
        if q:
            qf = fold(q)
            by_name = [p for p in notes if qf in fold(_title(p))]
            notes = by_name or [p for p in notes if qf in fold(p.read_text(encoding="utf-8", errors="replace"))]
        if not notes:
            return "Nessuna nota." if not q else f'Nessuna nota trovata per "{q}".'
        shown = notes[:12]
        refs = Refs.assign("nt", [str(p.relative_to(root)) for p in shown])
        return f"{len(notes)} note:\n" + "\n".join(f"[{r}] {_title(p)}" for r, p in zip(refs, shown))
    if sub in ("read", "leggi"):
        p = _resolve(args.pos[0] if args.pos else None)
        txt = p.read_text(encoding="utf-8", errors="replace").strip()
        return txt if len(txt) <= 4000 else txt[:4000] + " [...]"
    if sub in ("append", "aggiungi"):
        p = _resolve(args.pos[0] if args.pos else None)
        t = args.o("text", "testo")
        if not t:
            raise ToolError("uso: note append <nt1> --text T")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n" + t.replace("\\n", "\n") + "\n")
        ActionLog.add("NOTES", "Aggiornata nota")
        return "Testo aggiunto alla nota."
    raise ToolError("uso: note add|list|search|read|append")
