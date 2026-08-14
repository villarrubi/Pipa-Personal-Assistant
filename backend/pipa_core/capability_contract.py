"""Canonical public capability field contract shared by the Python layers.

The values describe metadata that may cross a device or mobile boundary. They
are deliberately separate from local application configuration and from the
integration handlers themselves.
"""

from __future__ import annotations

_CAPABILITY_GROUPS = frozenset({"web_search", "apple_music", "whatsapp", "discord", "league", "codex"})
_CAPABILITY_BOOLEAN_FIELDS = frozenset(
    {
        "available",
        "app_configured",
        "launcher_resolved",
        "search",
        "playback",
        "media_control",
        "requires_manual_selection",
        "open_web",
        "open_contact",
        "contact_aliases_configured",
        "prepare_message",
        "send_message",
        "requires_manual_send",
        "open_app",
        "open_channel",
        "start_call",
        "requires_manual_call",
        "client_ready",
        "open_client",
        "matchmaking",
        "cancel_matchmaking",
        "accept_match",
        "requires_manual_accept",
        "writes_to_chat",
        "requires_confirmation",
    }
)
_CAPABILITY_STRING_FIELDS = frozenset({"execution"})
_CAPABILITY_LIST_FIELDS = frozenset({"queues"})
