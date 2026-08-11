"""Safe WhatsApp Web compose links.

This module prepares a chat and message but never clicks Send and never reads
WhatsApp cookies, contacts, or message history.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from tools.urls import validate_external_url

MAX_MESSAGE_LENGTH = 4096
_PHONE_ALLOWED = re.compile(r"^[0-9]{7,15}$")


def normalize_phone(phone: str) -> str:
    if not isinstance(phone, str):
        raise ValueError("El teléfono debe ser texto.")
    normalized = re.sub(r"[\s().-]", "", phone.strip())
    if normalized.startswith("+"):
        normalized = normalized[1:]
    if _PHONE_ALLOWED.fullmatch(normalized) is None:
        raise ValueError("Usa un teléfono internacional con 7-15 dígitos.")
    return normalized


def build_whatsapp_compose_url(phone: str, message: str) -> str:
    normalized_phone = normalize_phone(phone)
    if not isinstance(message, str) or not message.strip():
        raise ValueError("El mensaje no puede estar vacío.")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"El mensaje no puede superar {MAX_MESSAGE_LENGTH} caracteres.")

    return validate_external_url(f"https://wa.me/{normalized_phone}?" + urlencode({"text": message}))
