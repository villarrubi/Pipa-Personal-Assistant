"""Safe WhatsApp Web navigation and compose links.

This module opens or prepares a chat but never clicks Send and never reads
WhatsApp cookies, contacts, or message history.
"""

from __future__ import annotations

import re
import webbrowser
from urllib.parse import urlencode

from tools.apps import AppsConfigError, open_app
from tools.browser import open_validated_url, without_destination
from tools.text_policy import validate_bounded_text
from tools.urls import validate_external_url

MAX_MESSAGE_LENGTH = 4096
WHATSAPP_WEB_URL = "https://web.whatsapp.com/"
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
    message = validate_bounded_text(
        message,
        "El mensaje",
        MAX_MESSAGE_LENGTH,
        allow_line_feed=True,
    )

    return validate_external_url(f"https://wa.me/{normalized_phone}?" + urlencode({"text": message}))


def open_whatsapp_compose(phone: str, message: str) -> dict[str, object]:
    """Open a pre-filled chat; sending always remains a human action."""

    return without_destination(
        open_validated_url(
            build_whatsapp_compose_url(phone, message),
            browser_open=webbrowser.open,
            success_message="Chat preparado; debes pulsar Enviar manualmente.",
            failure_message="No he podido abrir el chat de WhatsApp.",
        )
    ) | {"sent": False, "requires_manual_send": True}


def build_whatsapp_chat_url(phone: str) -> str:
    """Build a chat-only URL without pre-populating or sending a message."""

    return validate_external_url(f"https://wa.me/{normalize_phone(phone)}")


def open_whatsapp_chat(phone: str) -> dict[str, object]:
    """Open a chat without adding a message or sending anything."""

    return without_destination(
        open_validated_url(
            build_whatsapp_chat_url(phone),
            browser_open=webbrowser.open,
            success_message="Chat de WhatsApp abierto; no se ha preparado ni enviado ningún mensaje.",
            failure_message="No he podido abrir el chat de WhatsApp.",
        )
    ) | {"sent": False}


def build_whatsapp_web_url() -> str:
    return validate_external_url(WHATSAPP_WEB_URL)


def open_whatsapp_web() -> dict[str, object]:
    """Open an allowlisted desktop app or WhatsApp Web without sending."""

    try:
        app_result = open_app("whatsapp")
    except AppsConfigError:
        app_result = {"success": False}
    if app_result.get("success") is True:
        return {
            "success": True,
            "target": "desktop_app",
            "message": "WhatsApp abierto; no se ha enviado ningún mensaje.",
            "sent": False,
        }

    url = build_whatsapp_web_url()
    return without_destination(
        open_validated_url(
            url,
            browser_open=webbrowser.open,
            success_message="WhatsApp Web abierto; no se ha enviado ningún mensaje.",
            failure_message="No he podido abrir WhatsApp Web.",
        )
    ) | {"target": "web", "sent": False}
