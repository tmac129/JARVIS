"""Moduli opzionali, attivabili dal menu. Stato in modules.json, condiviso da app e comando `jarvis`."""
from __future__ import annotations

from enum import Enum

from .core import Store


class Module(str, Enum):
    mail = "mail"
    calendar = "calendar"
    reminders = "reminders"
    whatsapp = "whatsapp"
    notes = "notes"
    files = "files"
    music = "music"
    screen = "screen"

    @property
    def label(self) -> str:
        return {
            "mail": "Mail e contatti", "calendar": "Calendario", "reminders": "Promemoria", "whatsapp": "WhatsApp",
            "notes": "Note", "files": "File e documenti", "music": "Musica", "screen": "Schermo",
        }[self.value]

    @property
    def commands(self) -> set[str]:
        return {
            "mail": {"mail", "contact", "contatto"}, "calendar": {"cal", "calendar"},
            "reminders": {"rem", "reminder", "reminders"}, "whatsapp": {"wa", "whatsapp"},
            "notes": {"note", "notes"}, "files": {"file", "files", "doc", "docs"},
            "music": {"music", "musica"}, "screen": {"screen", "schermo"},
        }[self.value]

    @staticmethod
    def for_command(cmd: str) -> "Module | None":
        for m in Module:
            if cmd in m.commands:
                return m
        return None


class Modules:
    FILE = "modules.json"

    @staticmethod
    def disabled() -> set[str]:
        d = Store.load(Modules.FILE, {}) or {}
        return set(d.get("disabled", []))

    @staticmethod
    def is_enabled(m: Module) -> bool:
        return m.value not in Modules.disabled()

    @staticmethod
    def enabled() -> list[Module]:
        d = Modules.disabled()
        return [m for m in Module if m.value not in d]

    @staticmethod
    def set(m: Module, enabled: bool) -> None:
        d = Modules.disabled()
        if enabled:
            d.discard(m.value)
        else:
            d.add(m.value)
        Store.save(Modules.FILE, {"disabled": [x.value for x in Module if x.value in d]})

    @staticmethod
    def disabled_message(m: Module) -> str:
        return f"il modulo {m.label} è disattivato: riattivalo dal menu di JARVIS > Moduli"
