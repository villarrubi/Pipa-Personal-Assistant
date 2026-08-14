"""Prepare the ignored local contact aliases without exposing their values.

The agent itself only reads ``config/contacts.local.json``.  This helper is a
separate, explicit writer for that file: it validates the complete resulting
document with the same contact contract, preserves existing entries, and only
writes after the user passes ``--write``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.contacts import (  # noqa: E402
    LOCAL_CONTACTS_FILE,
    MAX_CONFIG_FILE_BYTES,
    ContactsConfigError,
    validate_contacts,
)

from backend.pipa_core.protocol import ProtocolError, parse_json_object  # noqa: E402


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as file:
            raw = file.read(MAX_CONFIG_FILE_BYTES + 1)
        if len(raw) > MAX_CONFIG_FILE_BYTES:
            raise ValueError("La configuración local es demasiado grande.")
        payload = parse_json_object(raw)
        validate_contacts(payload)
        return payload
    except (OSError, UnicodeDecodeError, ProtocolError, ContactsConfigError, ValueError) as error:
        raise ValueError("La configuración local de contactos no es válida.") from error


def _clean_aliases(name: str, aliases: list[str] | None) -> list[str]:
    values = [item.strip() for item in (aliases or []) if isinstance(item, str) and item.strip()]
    return values or [name]


def build_contact_payload(
    *,
    name: str,
    aliases: list[str] | None = None,
    whatsapp_phone: str | None = None,
    discord_channel_id: str | None = None,
    discord_guild_id: str | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a validated payload with one contact replaced or added."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("El nombre del contacto es obligatorio.")
    name = name.strip()
    payload = dict(existing or {})
    folded_name = _fold(name)
    for existing_name in list(payload):
        if isinstance(existing_name, str) and _fold(existing_name) == folded_name:
            del payload[existing_name]

    entry: dict[str, Any] = {"aliases": _clean_aliases(name, aliases)}
    if whatsapp_phone is not None and whatsapp_phone.strip():
        entry["whatsapp_phone"] = whatsapp_phone.strip()
    if discord_channel_id is not None and discord_channel_id.strip():
        entry["discord_channel_id"] = discord_channel_id.strip()
    if discord_guild_id is not None and discord_guild_id.strip():
        entry["discord_guild_id"] = discord_guild_id.strip()
    payload[name] = entry
    validate_contacts(payload)
    return payload


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace the ignored local file and leave no temp file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".contacts.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configura un alias local de WhatsApp y/o Discord para Pipa."
    )
    parser.add_argument("--name", help="Nombre local del contacto.")
    parser.add_argument("--alias", action="append", help="Alias adicional; puede repetirse.")
    parser.add_argument("--whatsapp-phone", help="Teléfono internacional de WhatsApp.")
    parser.add_argument("--discord-channel-id", help="ID numérico del canal o DM de Discord.")
    parser.add_argument("--discord-guild-id", help="ID numérico del servidor de Discord.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Escribe el archivo local. Sin esta opción solo valida y muestra un resumen.",
    )
    return parser


def _interactive_values(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.name:
        return {
            "name": arguments.name,
            "aliases": arguments.alias,
            "whatsapp_phone": arguments.whatsapp_phone,
            "discord_channel_id": arguments.discord_channel_id,
            "discord_guild_id": arguments.discord_guild_id,
        }

    name = input("Nombre local del contacto: ").strip()
    raw_aliases = input("Alias adicionales separados por coma (opcional): ").strip()
    aliases = [item.strip() for item in raw_aliases.split(",") if item.strip()] or None
    whatsapp_phone = input("Teléfono de WhatsApp (opcional): ").strip() or None
    discord_channel_id = input("ID de canal/DM de Discord (opcional): ").strip() or None
    discord_guild_id = (
        input("ID de servidor de Discord (opcional): ").strip() or None if discord_channel_id else None
    )
    return {
        "name": name,
        "aliases": aliases,
        "whatsapp_phone": whatsapp_phone,
        "discord_channel_id": discord_channel_id,
        "discord_guild_id": discord_guild_id,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        values = _interactive_values(arguments)
        existing = _read_payload(LOCAL_CONTACTS_FILE)
        payload = build_contact_payload(existing=existing, **values)
        if arguments.write:
            _write_payload(LOCAL_CONTACTS_FILE, payload)
            action = "guardado"
        else:
            action = "validado; no se ha escrito nada (usa --write para guardar)"
        contacts = validate_contacts(payload)
        contact = next(
            contact for contact in contacts.values() if _fold(contact.name) == _fold(values["name"].strip())
        )
        destinations = []
        if contact.whatsapp_phone is not None:
            destinations.append("WhatsApp")
        if contact.discord_channel_id is not None:
            destinations.append("Discord")
        print(f"Contacto {action}. Destinos: {', '.join(destinations)}.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Configuración cancelada.", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("No se pudo validar o guardar la configuración local de contactos.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
