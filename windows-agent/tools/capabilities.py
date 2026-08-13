"""Read-only capability reporting for the local Windows Agent.

The response is descriptive rather than permissive: it tells a UI what can
be prepared and what still needs a human action. It never exposes application
commands, League credentials, URLs, contacts, or message text.
"""

from __future__ import annotations

from typing import Any

from tools.apps import AppsConfigError, load_apps
from tools.contacts import ContactsConfigError, load_contacts
from tools.integration_catalog import build_integration_capabilities, get_command_catalog
from tools.league import LeagueClientError, find_client_connection


def _configured_apps() -> dict[str, bool]:
    try:
        apps = load_apps()
    except AppsConfigError:
        return {"apple_music": False, "league_of_legends": False, "codex": False}
    app_ids = {app_id.strip().lower() for app_id in apps}
    return {
        "apple_music": "apple_music" in app_ids,
        "league_of_legends": "league_of_legends" in app_ids,
        "codex": "codex" in app_ids,
    }


def _league_client_ready() -> bool:
    try:
        # Discovery is used only to report readiness. The token is discarded
        # immediately and is never part of the returned capability document.
        find_client_connection()
    except LeagueClientError:
        return False
    return True


def _configured_contact_destinations() -> tuple[bool, bool]:
    """Report alias availability without exposing names or destinations."""

    try:
        contacts = load_contacts()
    except ContactsConfigError:
        return False, False

    return (
        any(contact.whatsapp_phone is not None for contact in contacts.values()),
        any(contact.discord_channel_id is not None for contact in contacts.values()),
    )


def get_integration_capabilities() -> dict[str, dict[str, Any]]:
    """Return only the public integration matrix shared with local UIs."""

    configured = _configured_apps()
    league_ready = configured["league_of_legends"] and _league_client_ready()
    whatsapp_contacts_configured, discord_contacts_configured = _configured_contact_destinations()
    return build_integration_capabilities(
        apple_music_configured=configured["apple_music"],
        league_available=configured["league_of_legends"],
        league_ready=league_ready,
        codex_configured=configured["codex"],
        whatsapp_contacts_configured=whatsapp_contacts_configured,
        discord_contacts_configured=discord_contacts_configured,
    )


def get_mobile_capabilities() -> dict[str, dict[str, Any]]:
    """Return the bounded capability matrix suitable for the device catalog."""

    return get_integration_capabilities()


def get_capabilities(
    *,
    serial_gateway_configured: bool,
    serial_gateway_running: bool,
    serial_gateway_connected: bool = False,
    mobile_gateway_configured: bool = False,
    mobile_gateway_running: bool = False,
    mobile_gateway_connected: bool = False,
) -> dict[str, Any]:
    """Return a stable, non-sensitive feature matrix for local UIs and CLI."""

    return {
        "success": True,
        "hardware_required": False,
        "device": {
            "serial_gateway_configured": serial_gateway_configured,
            "serial_gateway_running": serial_gateway_running,
            "serial_gateway_connected": serial_gateway_connected,
            "mobile_gateway_configured": mobile_gateway_configured,
            "mobile_gateway_running": mobile_gateway_running,
            "mobile_gateway_connected": mobile_gateway_connected,
            "mobile_transport_security": "secure-session-v2",
        },
        "integrations": get_integration_capabilities(),
        "commands": get_command_catalog(),
    }
