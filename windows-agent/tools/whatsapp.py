"""WhatsApp delivery adapters.

Manual mode opens a compose link and never clicks Send. The optional automatic
mode uses Meta's server-side Cloud API with an access token kept outside the
JSON configuration; it never automates keyboard or browser focus.
"""

from __future__ import annotations

import json
import re
import webbrowser
from urllib import error, request
from urllib.parse import urlencode

from tools.apps import AppsConfigError, open_app
from tools.browser import open_validated_url, without_destination
from tools.control_config import (
    get_whatsapp_access_token,
    get_whatsapp_settings,
)
from tools.text_policy import validate_bounded_text
from tools.urls import validate_external_url

MAX_MESSAGE_LENGTH = 4096
WHATSAPP_WEB_URL = "https://web.whatsapp.com/"
_PHONE_ALLOWED = re.compile(r"^[1-9][0-9]{6,14}$")
_PHONE_FORMATTING = re.compile(r"[ ().-]")
MAX_CLOUD_RESPONSE_BYTES = 64 * 1024


def normalize_phone(phone: str) -> str:
    if not isinstance(phone, str):
        raise ValueError("El teléfono debe ser texto.")
    # Keep this formatting set identical to PipaMobileDestinationPolicy:
    # invisible Unicode spacing must not change the destination differently
    # on Windows and iPhone.
    normalized = _PHONE_FORMATTING.sub("", phone.strip())
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


def send_whatsapp_cloud_message(phone: str, message: str) -> dict[str, object]:
    """Send one text message through the explicitly configured Cloud API."""

    normalized_phone = normalize_phone(phone)
    message = validate_bounded_text(
        message,
        "El mensaje",
        MAX_MESSAGE_LENGTH,
        allow_line_feed=True,
    )
    settings = get_whatsapp_settings()
    token = get_whatsapp_access_token()
    phone_number_id = settings["phone_number_id"]
    if settings["mode"] != "cloud_api" or not phone_number_id or token is None:
        return {
            "success": False,
            "sent": False,
            "requires_manual_send": False,
            "message": "El envío automático de WhatsApp no está configurado.",
        }

    endpoint = validate_external_url(
        f"https://graph.facebook.com/{settings['api_version']}/{phone_number_id}/messages"
    )
    body = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    cloud_request = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Pipa-Windows-Agent/0.5",
        },
    )
    try:
        with request.urlopen(cloud_request, timeout=15) as response:  # nosec B310
            status = getattr(response, "status", response.getcode())
            response_body = response.read(MAX_CLOUD_RESPONSE_BYTES + 1)
        if not 200 <= status < 300 or len(response_body) > MAX_CLOUD_RESPONSE_BYTES:
            raise RuntimeError("unexpected Cloud API response")
    except (OSError, error.HTTPError, error.URLError, RuntimeError):
        return {
            "success": False,
            "sent": False,
            "requires_manual_send": False,
            "message": "WhatsApp no ha confirmado el envío automático.",
        }
    return {
        "success": True,
        "sent": True,
        "requires_manual_send": False,
        "delivery": "cloud_api",
        "message": "Mensaje enviado automáticamente por WhatsApp Cloud API.",
    }


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
