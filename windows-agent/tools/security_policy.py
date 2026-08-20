"""Shared local-agent security policy.

Keeping the path allowlist in one module prevents the HTTP server and the
local CLI from drifting apart when a new outward-facing action is added.
"""

from __future__ import annotations

# Keep the tool-to-route relationship explicit. Diagnostics can then detect a
# new outward-facing tool that was added without the local confirmation wall.
CONFIRMATION_TOOL_PATHS = {
    "open_app": "/open-app",
    "open_url": "/open-url",
    "web_search": "/web/search",
    "music_open": "/music/open",
    "music_search": "/music/search",
    "league_open": "/league/open",
    "league_search": "/league/search",
    "league_cancel": "/league/search",
    "whatsapp_open": "/whatsapp/open",
    "whatsapp_compose": "/whatsapp/compose",
    "whatsapp_contact": "/whatsapp/contact/compose",
    "whatsapp_contact_open": "/whatsapp/contact/open",
    "whatsapp_phone_open": "/whatsapp/phone/open",
    "discord_open_app": "/discord/open",
    "discord_open": "/discord/channel/open",
    "discord_call_channel": "/discord/channel/call",
    "discord_contact": "/discord/contact/open",
    "discord_call": "/discord/contact/call",
    "open_codex": "/codex/open",
    "system_lock": "/system/lock",
    "system_sleep": "/system/sleep",
}

LOCAL_CONFIRMATION_PATHS = frozenset(CONFIRMATION_TOOL_PATHS.values())

# The local CLI is another execution surface. Keep its confirmation gate in
# this module so adding a command cannot silently create a less protected CLI
# path than the REST endpoint and the authenticated Core.
CLI_CONFIRMATION_COMMANDS = frozenset(
    {
        "open-app",
        "codex-open",
        "web-search",
        "open-url",
        "music-open",
        "music-search",
        "whatsapp-open",
        "whatsapp-compose",
        "whatsapp-contact",
        "whatsapp-contact-open",
        "whatsapp-phone-open",
        "discord-open",
        "discord-channel",
        "discord-call-channel",
        "discord-contact",
        "discord-call",
        "league-open",
        "league-search",
        "league-cancel",
        "lock",
        "sleep",
    }
)
