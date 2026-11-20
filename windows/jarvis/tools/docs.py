"""Lettura di documenti: PDF, Word (.docx), RTF, OpenDocument (.odt), testo e immagini."""
from __future__ import annotations

import os
import re
import time
import zipfile
from pathlib import Path

from ..core import ActionLog, Args, Paths, ToolError
from .files import resolve_existing


def view_dir() -> Path:
    d = Paths.support / "view"
    d.mkdir(parents=True, exist_ok=True)
    # tenerla piccola: via i file piu' vecchi di 2 ore
    for f in d.iterdir():
        try:
            if time.time() - f.stat().st_mtime > 7200:
                f.unlink()
        except OSError:
            pass
    return d


def _read_text(path: str) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return Path(path).read_text(encoding=enc)
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def _pdf(path: str, args: Args, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ToolError("libreria pypdf mancante: esegui `pip install -e .`")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ToolError("PDF protetto da password")
        total = len(reader.pages)
    except ToolError:
        raise
    except Exception:
        raise ToolError("PDF non leggibile")
    first, last = 1, total
    p = args.o("pages", "pagine")
    if p:
        nums = [int(x) for x in re.findall(r"\d+", p)]
        if nums:
            first = max(1, nums[0])
            last = min(total, nums[1] if len(nums) > 1 else nums[0])
    text = ""
    for i in range(first - 1, last):
        s = (reader.pages[i].extract_text() or "").strip()
        if s:
            text += f"\n--- pagina {i + 1} ---\n" + s
        if len(text) > max_chars:
            break
    if not text.strip():
        # PDF scansionato: disegno le pagine come immagini, da guardare con lo strumento Read
        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise ToolError("PDF scansionato senza testo e libreria pypdfium2 mancante")
        outs = []
        pdf = pdfium.PdfDocument(path)
        try:
            for i in range(first - 1, min(last, first + 2)):
                img = pdf[i].render(scale=1.6).to_pil().convert("RGB")
                img.thumbnail((1400, 1800))
                out = view_dir() / f"pdf-{i + 1}-{int(time.time())}.jpg"
                img.save(out, "JPEG", quality=70)
                outs.append(str(out))
        finally:
            pdf.close()
        return (f"PDF scansionato senza testo ({total} pagine). Immagini delle pagine: {' '.join(outs)}. "
                "Guardale con lo strumento Read.")
    return f"PDF di {total} pagine" + text


def _docx(path: str) -> str:
    try:
        from docx import Document
    except ImportError:
        raise ToolError("libreria python-docx mancante: esegui `pip install -e .`")
    d = Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def _odt(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</text:(p|h)>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _image(path: str) -> str:
    try:
        from PIL import Image
    except ImportError:
        raise ToolError("libreria Pillow mancante: esegui `pip install -e .`")
    img = Image.open(path).convert("RGB")
    img.thumbnail((1600, 1600))
    out = view_dir() / f"img-{int(time.time())}.jpg"
    img.save(out, "JPEG", quality=85)
    return f"Immagine pronta: {out}. Guardala con lo strumento Read."


def run(a: list[str]) -> str:
    args = Args(a[1:])
    if not a or a[0] not in ("read", "leggi") or not args.pos:
        raise ToolError("uso: doc read <f1|percorso> [--pages 1-5]")
    path = resolve_existing(" ".join(args.pos))
    ext = Path(path).suffix.lower().lstrip(".")
    try:
        max_chars = int(args.o("max") or 12000)
    except ValueError:
        max_chars = 12000
    if ext == "pdf":
        text = _pdf(path, args, max_chars)
        if text.startswith("PDF scansionato"):
            return text
    elif ext in ("png", "jpg", "jpeg", "gif", "tiff", "tif", "bmp", "webp", "heic"):
        return _image(path)
    elif ext in ("txt", "md", "csv", "json", "py", "js", "html", "xml", "log", "ini", "yaml", "yml"):
        text = _read_text(path)
    elif ext == "docx":
        text = _docx(path)
    elif ext == "rtf":
        from striprtf.striprtf import rtf_to_text
        text = rtf_to_text(_read_text(path))
    elif ext == "odt":
        text = _odt(path)
    else:
        raise ToolError(f"formato .{ext} non supportato (salva il file come PDF, DOCX o testo)")
    ActionLog.add("DOCUMENTS", f"Letto {os.path.basename(path)}")
    clean = re.sub(r"\n{3,}", "\n\n", text)
    return clean if len(clean) <= max_chars else clean[:max_chars] + "\n[... troncato: usa --pages per altre parti]"
