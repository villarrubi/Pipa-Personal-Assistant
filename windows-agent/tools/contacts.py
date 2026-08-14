"""Optional local aliases for human-assisted WhatsApp and Discord actions.

The file is deliberately local-only.  Pipa uses an alias to prepare a chat or
open a Discord channel, but it never sends a WhatsApp message or presses a
Discord call button.  Contact identifiers are therefore kept out of the
catalog, capabilities, logs, and device result envelopes.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.pipa_core.protocol import ProtocolError, parse_json_object
from tools.discord import build_discord_channel_url
from tools.whatsapp import normalize_phone

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOCAL_CONTACTS_FILE = CONFIG_DIR / "contacts.local.json"
MAX_CONTACTS = 64
MAX_CONFIG_FILE_BYTES = 128 * 1024
MAX_ALIASES_PER_CONTACT = 16
MAX_ALIAS_LENGTH = 80
_CONTACT_FIELDS = frozenset({"aliases", "whatsapp_phone", "discord_channel_id", "discord_guild_id"})


class ContactsConfigError(ValueError):
    """La configuración local de contactos no tiene el formato esperado."""


@dataclass(frozen=True)
class Contact:
    """Validated contact destination without exposing it in public metadata."""

    name: str
    aliases: tuple[str, ...]
    whatsapp_phone: str | None
    discord_channel_id: str | None
    discord_guild_id: str | None


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _text(value: Any, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ContactsConfigError(f"{field_name} debe ser texto.")
    value = value.strip()
    if not value or len(value) > maximum or any(_is_forbidden_label_character(char) for char in value):
        raise ContactsConfigError(f"{field_name} no es válido.")
    return value


def _is_forbidden_label_character(character: str) -> bool:
    """Reject controls and invisible formatting from contact labels.

    Contact aliases are displayed in confirmation prompts.  Blocking Unicode
    formatting controls prevents look-alike or right-to-left overrides from
    changing what the user thinks they are authorizing.  Message bodies are
    intentionally not passed through this validator because WhatsApp text may
    legitimately contain line breaks and formatting.
    """

    return unicodedata.category(character) in {"Cc", "Cf", "Cs", "Co", "Cn"}


def validate_contacts(payload: Any) -> dict[str, Contact]:
    if not isinstance(payload, dict) or len(payload) > MAX_CONTACTS:
        raise ContactsConfigError("Los contactos deben ser un objeto de tamaño limitado.")

    contacts: dict[str, Contact] = {}
    seen_labels: dict[str, str] = {}
    for raw_name, raw_data in payload.items():
        name = _text(raw_name, "El nombre del contacto", maximum=MAX_ALIAS_LENGTH)
        if not isinstance(raw_data, dict):
            raise ContactsConfigError(f"Configuración inválida para '{name}'.")
        if set(raw_data) - _CONTACT_FIELDS:
            raise ContactsConfigError(f"Hay campos desconocidos para '{name}'.")

        aliases_value = raw_data.get("aliases", [name])
        if (
            not isinstance(aliases_value, list)
            or not aliases_value
            or len(aliases_value) > MAX_ALIASES_PER_CONTACT
        ):
            raise ContactsConfigError(f"Aliases inválidos para '{name}'.")
        aliases = tuple(_text(alias, "El alias", maximum=MAX_ALIAS_LENGTH) for alias in aliases_value)
        aliases = tuple(dict.fromkeys(aliases))

        phone_value = raw_data.get("whatsapp_phone")
        whatsapp_phone = None
        if phone_value is not None:
            try:
                whatsapp_phone = normalize_phone(_text(phone_value, "whatsapp_phone", maximum=32))
            except ValueError as error:
                raise ContactsConfigError(f"Teléfono inválido para '{name}'.") from error

        channel_value = raw_data.get("discord_channel_id")
        guild_value = raw_data.get("discord_guild_id")
        discord_channel_id = None
        discord_guild_id = None
        if channel_value is not None:
            discord_channel_id = _text(channel_value, "discord_channel_id", maximum=20)
            if guild_value is not None:
                discord_guild_id = _text(guild_value, "discord_guild_id", maximum=20)
            try:
                build_discord_channel_url(discord_channel_id, discord_guild_id)
            except ValueError as error:
                raise ContactsConfigError(f"Canal Discord inválido para '{name}'.") from error
        elif guild_value is not None:
            raise ContactsConfigError(f"discord_guild_id requiere discord_channel_id para '{name}'.")

        if whatsapp_phone is None and discord_channel_id is None:
            raise ContactsConfigError(f"'{name}' no tiene ningún destino configurado.")

        folded_name = _fold(name)
        previous_name = seen_labels.get(folded_name)
        if previous_name is not None:
            raise ContactsConfigError(f"El nombre o alias '{name}' está repetido.")
        contact = Contact(name, aliases, whatsapp_phone, discord_channel_id, discord_guild_id)
        contacts[folded_name] = contact
        seen_labels[folded_name] = name
        for alias in aliases:
            folded = _fold(alias)
            if folded == folded_name:
                continue
            previous = seen_labels.get(folded)
            if previous is not None:
                raise ContactsConfigError(f"El alias '{alias}' está repetido.")
            seen_labels[folded] = name
    return contacts


def load_contacts() -> dict[str, Contact]:
    """Load only the ignored local file; absence means no aliases configured."""

    if not LOCAL_CONTACTS_FILE.exists():
        return {}
    try:
        with LOCAL_CONTACTS_FILE.open("rb") as file:
            raw = file.read(MAX_CONFIG_FILE_BYTES + 1)
        if len(raw) > MAX_CONFIG_FILE_BYTES:
            raise ContactsConfigError("La configuración de contactos es demasiado grande.")
        return validate_contacts(parse_json_object(raw))
    except OSError as error:
        raise ContactsConfigError("No se pudo leer la configuración local de contactos.") from error
    except UnicodeDecodeError as error:
        raise ContactsConfigError("La configuración local de contactos no es UTF-8 válido.") from error
    except ProtocolError as error:
        raise ContactsConfigError("La configuración local de contactos no es JSON válido.") from error


def _find(alias: str) -> Contact:
    try:
        query = _text(alias, "El contacto", maximum=MAX_ALIAS_LENGTH)
    except ContactsConfigError as error:
        raise ValueError("El contacto no es válido.") from error
    contacts = load_contacts()
    folded = _fold(query)
    for contact in contacts.values():
        if folded == _fold(contact.name) or any(folded == _fold(item) for item in contact.aliases):
            return contact
    raise ValueError("No existe ese contacto local.")


def resolve_whatsapp_contact(alias: str) -> tuple[str, str]:
    contact = _find(alias)
    if contact.whatsapp_phone is None:
        raise ValueError("Ese contacto no tiene WhatsApp configurado.")
    return contact.name, contact.whatsapp_phone


def resolve_discord_contact(alias: str) -> tuple[str, str, str | None]:
    contact = _find(alias)
    if contact.discord_channel_id is None:
        raise ValueError("Ese contacto no tiene Discord configurado.")
    return contact.name, contact.discord_channel_id, contact.discord_guild_id
