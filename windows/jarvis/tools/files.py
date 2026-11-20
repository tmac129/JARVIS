"""File e cartelle: cerca, elenca, sposta, copia, rinomina, crea cartella, apri, mostra, cestina."""
from __future__ import annotations

import glob as globmod
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .. import gate
from ..core import IS_WINDOWS, ActionLog, Args, Paths, Refs, ToolError, fold

BULK_LIMIT = 25

# Aprire questi file esegue codice: eseguibili, script, installer, macro, scorciatoie e collegamenti.
RISKY_EXT = {
    "exe", "com", "scr", "bat", "cmd", "ps1", "psm1", "psd1", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta",
    "msi", "msp", "msix", "appx", "appxbundle", "appinstaller", "lnk", "url", "reg", "inf", "cpl", "dll", "sys",
    "jar", "py", "pyw", "pl", "rb", "php", "sh", "zsh", "bash", "docm", "xlsm", "pptm", "dotm", "xlam", "iso",
    "settingcontent-ms", "pif", "gadget", "application", "msc", "theme", "themepack",
}

SKIP_DIRS = {"node_modules", "$recycle.bin", "system volume information", "appdata", "windows", "program files",
             "program files (x86)", "programdata", "__pycache__", ".git"}


def _roots_sensitive() -> list[str]:
    roots = []
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "ProgramW6432"):
        v = os.environ.get(var)
        if v:
            roots.append(os.path.normcase(os.path.normpath(v)))
    if not IS_WINDOWS:
        roots += ["/etc", "/usr", "/bin", "/sbin", "/System", "/Library", "/Applications", "/private/etc"]
    home = Path.home()
    roots += [os.path.normcase(str(home / "AppData")), os.path.normcase(str(home / "Library"))]
    return roots


def is_sensitive(d: str) -> bool:
    """Cartelle di sistema, AppData (li' si installa la persistenza) e cartelle nascoste come ~/.ssh."""
    p = os.path.normcase(os.path.realpath(d))
    if any(p == r or p.startswith(r + os.sep) for r in _roots_sensitive()):
        return True
    home = os.path.normcase(os.path.realpath(str(Path.home())))
    if p.startswith(home + os.sep):
        return any(part.startswith(".") for part in p[len(home) + 1:].split(os.sep))
    return False


def is_risky(path: str) -> bool:
    return Path(path).suffix.lower().lstrip(".") in RISKY_EXT


def resolve(s: str) -> str:
    r = Refs.resolve(s)
    return r if r else Paths.expand(s)


def resolve_existing(s: str) -> str:
    p = resolve(s)
    if not os.path.exists(p):
        raise ToolError(f"file non trovato: {s}")
    return p


def expand_sources(items: list[str]) -> list[str]:
    out: list[str] = []
    for it in items:
        r = Refs.resolve(it)
        if r:
            out.append(r)
            continue
        p = Paths.expand(it)
        if "*" in p or "?" in p:
            out += sorted(globmod.glob(p))
        elif os.path.exists(p):
            out.append(p)
        else:
            raise ToolError(f"non trovato: {it}")
    return out


def unique(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} {i}{ext}"):
        i += 1
    return f"{base} {i}{ext}"


def mtime(p: str) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _size(n: float) -> str:
    if n < 1000:
        return f"{int(n)} byte"
    for unit in ("KB", "MB", "GB"):
        n /= 1000
        if n < 1000 or unit == "GB":
            return f"{n:.1f} {unit}".replace(".0 ", " ")
    return str(n)


def describe(paths: list[str], prefix: str) -> str:
    refs = Refs.assign(prefix, paths)
    rows = []
    for ref, p in zip(refs, paths):
        size = "cartella" if os.path.isdir(p) else _size(os.path.getsize(p) if os.path.exists(p) else 0)
        rows.append(f"[{ref}] {Paths.pretty(p)} ({size}, {datetime.fromtimestamp(mtime(p)):%Y-%m-%d})")
    return "\n".join(rows)


def walk(roots: list[str], name: str, ext: str | None, days: float | None, dirs_only: bool,
         budget_s: float = 15.0, cap: int = 300000) -> list[str]:
    """Ricerca diretta nelle cartelle, con tetto di tempo e di elementi (sostituisce Spotlight)."""
    since = time.time() - days * 86400 if days is not None else None
    needle = fold(name)
    out, seen, deadline = [], 0, time.time() + budget_s
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not d.startswith(".") and d.lower() not in SKIP_DIRS]
            names = dns if dirs_only else dns + fns
            for n in names:
                seen += 1
                if needle and needle not in fold(n):
                    continue
                if ext and not n.lower().endswith("." + ext):
                    continue
                full = os.path.join(dp, n)
                if dirs_only and not os.path.isdir(full):
                    continue
                if since is not None and mtime(full) < since:
                    continue
                out.append(full)
            if seen > cap or time.time() > deadline:
                return sorted(set(out), key=mtime, reverse=True)
    return sorted(set(out), key=mtime, reverse=True)


def _trash(paths: list[str]) -> None:
    try:
        from send2trash import send2trash
    except ImportError:
        raise ToolError("libreria send2trash mancante: esegui `pip install -e .` nella cartella windows")
    for p in paths:
        send2trash(p)


def run(a: list[str], confirmed: bool = False, raw: list[str] | None = None) -> str:
    raw = raw or []
    if not a:
        raise ToolError("uso: file find|ls|move|copy|rename|mkdir|open|reveal|trash")
    sub = a[0]
    args = Args(a[1:], flags={"dirs", "all"})
    if sub in ("find", "cerca"):
        q = " ".join(args.pos)
        home = str(Path.home())
        in_dir = Paths.expand(args.o("in", "dir")) if args.o("in", "dir") else None
        ext = (args.o("ext") or "").lower().strip(".") or None
        days = None
        try:
            d = float(args.o("days", "giorni")) if args.o("days", "giorni") else None
            days = d if d is not None and 0 <= d < 36500 else None
        except ValueError:
            days = None
        try:
            limit = int(args.o("n", "max") or 15)
        except ValueError:
            limit = 15
        if not q and not ext and days is None and not args.has("dirs"):
            raise ToolError("uso: file find <nome> [--ext pdf] [--in DIR] [--days N] [--dirs]")
        if in_dir:
            roots = [in_dir]
        else:
            roots = [str(Paths.known_folder(n)) for n in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")]
            roots = list(dict.fromkeys(r for r in roots if os.path.isdir(r)))
        paths = walk(roots, q, ext, days, args.has("dirs"))
        if not paths and not in_dir:
            paths = walk([home], q, ext, days, args.has("dirs"), budget_s=10)
        if not paths:
            return "Nessun file trovato."
        shown = paths[:limit]
        more = f" (mostro {len(shown)})" if len(paths) > len(shown) else ""
        return f"{len(paths)} trovati{more}:\n" + describe(shown, "f")
    if sub in ("ls", "list"):
        d = Paths.expand(args.pos[0] if args.pos else "~/Desktop")
        ext = (args.o("ext") or "").lower().strip(".") or None
        if not os.path.isdir(d):
            raise ToolError(f"cartella non trovata: {Paths.pretty(d)}")
        items = [n for n in os.listdir(d) if not n.startswith(".")]
        if ext:
            items = [n for n in items if n.lower().endswith("." + ext)]
        paths = sorted((os.path.join(d, n) for n in items), key=mtime, reverse=True)
        if not paths:
            return f"{Paths.pretty(d)} è vuota" + (f" (per .{ext})" if ext else "") + "."
        shown = paths[:200 if args.has("all") else 40]
        more = f" (mostro {len(shown)})" if len(paths) > len(shown) else ""
        return f"{Paths.pretty(d)}: {len(paths)} elementi{more}:\n" + describe(shown, "f")
    if sub in ("move", "mv", "sposta", "copy", "cp", "copia"):
        copy = sub in ("copy", "cp", "copia")
        dest_raw = args.o("to", "in", "dest")
        if not dest_raw:
            raise ToolError("manca --to <cartella>")
        dest = resolve(dest_raw)
        if not os.path.isdir(dest):
            raise ToolError(f"la cartella {Paths.pretty(dest)} non esiste: creala con `file mkdir` o cercala con `file find <nome> --dirs`")
        sources = expand_sources(args.pos)
        if not sources:
            raise ToolError("nessun file corrisponde")
        verb = "Copiare" if copy else "Spostare"
        hidden = any(os.path.basename(s).startswith(".") for s in sources)
        # anche quando i file vengono DA una cartella di sistema o di configurazione (es. copiare ~/.ssh/id_ed25519)
        from_sensitive = any(is_sensitive(os.path.dirname(s)) for s in sources)
        if (len(sources) > BULK_LIMIT or is_sensitive(dest) or from_sensitive or hidden) and not confirmed:
            why = " (cartella di sistema o di configurazione)" if is_sensitive(dest) or from_sensitive else (" (file nascosti)" if hidden else "")
            return gate.request(f"{verb} {len(sources)} elementi in {Paths.pretty(dest)}{why}", raw)
        done = []
        for s in sources:
            target = unique(os.path.join(dest, os.path.basename(s)))
            if copy:
                shutil.copytree(s, target) if os.path.isdir(s) else shutil.copy2(s, target)
            else:
                shutil.move(s, target)
            done.append(os.path.basename(target))
        what = done[0] if len(done) == 1 else f"{len(done)} elementi"
        ActionLog.add("FILE_SYSTEM", f"{'Copiato' if copy else 'Spostato'} {what} in {Paths.pretty(dest)}")
        return f"{'Copiat' if copy else 'Spostat'}{'o' if len(done) == 1 else 'i'} {what} in {Paths.pretty(dest)}."
    if sub in ("rename", "rinomina"):
        if len(args.pos) < 2:
            raise ToolError("uso: file rename <SRC> <nuovo nome>")
        src = resolve_existing(args.pos[0])
        new_name = " ".join(args.pos[1:])
        old_ext = Path(src).suffix
        if not Path(new_name).suffix and old_ext:
            new_name += old_ext
        if "/" in new_name or "\\" in new_name:
            raise ToolError("il nuovo nome non può contenere / o \\")
        new_ext = Path(new_name).suffix.lower().lstrip(".")
        if (new_name.startswith(".") or is_sensitive(os.path.dirname(src))
                or (new_ext in RISKY_EXT and new_ext != old_ext.lower().lstrip("."))) and not confirmed:
            return gate.request(f"Rinominare {os.path.basename(src)} in {new_name}", raw)
        target = os.path.join(os.path.dirname(src), new_name)
        if os.path.exists(target):
            raise ToolError(f"esiste già {new_name}")
        os.rename(src, target)
        ActionLog.add("FILE_SYSTEM", f"Rinominato {os.path.basename(src)} in {new_name}")
        return f"Rinominato in {new_name}."
    if sub in ("mkdir", "crea"):
        if not args.pos:
            raise ToolError("uso: file mkdir <percorso>")
        path = Paths.expand(" ".join(args.pos))
        os.makedirs(path, exist_ok=True)
        ActionLog.add("FILE_SYSTEM", f"Creata cartella {Paths.pretty(path)}")
        return f"Creata {Paths.pretty(path)}."
    if sub in ("open", "apri", "reveal", "mostra"):
        src = resolve_existing(" ".join(args.pos))
        reveal = sub in ("reveal", "mostra")
        if not reveal and is_risky(src) and not confirmed:
            return gate.request(f"Aprire {os.path.basename(src)} (app, script o file eseguibile)", raw)
        if IS_WINDOWS:
            if reveal:
                subprocess.Popen(["explorer.exe", "/select,", src])
            else:
                os.startfile(src)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open", "-R", src] if reveal else ["open", src])
        ActionLog.add("FILE_SYSTEM", f"{'Mostrato' if reveal else 'Aperto'} {os.path.basename(src)}")
        return f"{'Mostrato in Esplora risorse' if reveal else 'Aperto'} {os.path.basename(src)}."
    if sub in ("trash", "cestina"):
        sources = expand_sources(args.pos)
        if not sources:
            raise ToolError("nessun file corrisponde")
        names = ", ".join(os.path.basename(s) for s in sources[:5]) + ("..." if len(sources) > 5 else "")
        if not confirmed:
            return gate.request(f"Spostare nel Cestino {names}" if len(sources) == 1 else
                                f"Spostare nel Cestino {len(sources)} elementi ({names})", raw)
        _trash(sources)
        ActionLog.add("FILE_SYSTEM", f"Cestinati {len(sources)} elementi")
        return (f"Spostato nel Cestino {os.path.basename(sources[0])}." if len(sources) == 1
                else f"Spostati nel Cestino {len(sources)} elementi.")
    raise ToolError(f"sottocomando file sconosciuto: {sub}")
