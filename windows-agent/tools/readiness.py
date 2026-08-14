"""Safe, side-effect-free readiness report for the local integrations.

This report joins the two pieces a user needs before trying WhatsApp, Discord,
Apple Music or League: whether the local app configuration is usable and
whether private contact aliases exist.  It intentionally returns counts and
booleans only; phone numbers, Discord IDs, commands and paths never leave the
agent.
"""

from __future__ import annotations

from typing import Any

from tools.app_diagnostics import inspect_apps
from tools.apps import AppsConfigError
from tools.capabilities import get_integration_capabilities
from tools.contacts import ContactsConfigError, load_contacts


def inspect_contacts() -> dict[str, Any]:
    """Summarize local aliases without returning names or destinations."""

    try:
        contacts = load_contacts()
    except ContactsConfigError:
        return {
            "success": False,
            "configured_count": 0,
            "whatsapp_destinations": 0,
            "discord_destinations": 0,
            "error": "contacts_config_invalid",
        }

    return {
        "success": True,
        "configured_count": len(contacts),
        "whatsapp_destinations": sum(contact.whatsapp_phone is not None for contact in contacts.values()),
        "discord_destinations": sum(contact.discord_channel_id is not None for contact in contacts.values()),
    }


def inspect_readiness() -> dict[str, Any]:
    """Return a bounded readiness report without launching or contacting apps."""

    apps = inspect_apps()
    contacts = inspect_contacts()
    try:
        integrations = get_integration_capabilities()
    except (AppsConfigError, ContactsConfigError, OSError, ValueError):
        return {
            "success": False,
            "apps": apps,
            "contacts": contacts,
            "integrations": {},
            "error": "integrations_unavailable",
        }

    return {
        "success": bool(apps.get("success")) and bool(contacts.get("success")),
        "apps": apps,
        "contacts": contacts,
        "integrations": integrations,
    }
