"""Shared local-agent security policy.

Keeping the path allowlist in one module prevents the HTTP server and the
local CLI from drifting apart when a new outward-facing action is added.
"""

from __future__ import annotations

LOCAL_CONFIRMATION_PATHS = frozenset(
    {
        "/open-app",
        "/open-url",
        "/web/search",
        "/music/open",
        "/music/search",
        "/league/open",
        "/league/search",
        "/whatsapp/open",
        "/whatsapp/compose",
        "/whatsapp/contact/compose",
        "/whatsapp/contact/open",
        "/discord/open",
        "/discord/channel/open",
        "/discord/contact/open",
        "/discord/contact/call",
        "/codex/open",
        "/system/lock",
    }
)

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
        "discord-open",
        "discord-channel",
        "discord-contact",
        "discord-call",
        "league-open",
        "league-search",
        "league-cancel",
        "lock",
    }
)
