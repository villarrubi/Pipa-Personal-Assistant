"""Safe Discord navigation helpers.

The agent can open a known Discord DM or channel. It deliberately does not
automate a personal Discord account, scrape contacts, or click call buttons.
"""

from __future__ import annotations

import re
import webbrowser

from tools.urls import validate_external_url


_SNOWFLAKE = re.compile(r"^[0-9]{17,20}$")


def _validate_snowflake(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SNOWFLAKE.fullmatch(value.strip()) is None:
        raise ValueError(f"{field_name} debe ser un ID de Discord válido.")
    return value.strip()


def build_discord_channel_url(channel_id: str, guild_id: str | None = None) -> str:
    """Build a Discord URL for a DM, group DM, or server channel."""
    channel = _validate_snowflake(channel_id, "channel_id")
    guild = "@me" if guild_id is None else _validate_snowflake(guild_id, "guild_id")
    return validate_external_url(f"https://discord.com/channels/{guild}/{channel}")


def open_discord_channel(channel_id: str, guild_id: str | None = None) -> dict[str, object]:
    url = build_discord_channel_url(channel_id, guild_id)
    webbrowser.open(url)
    return {
        "success": True,
        "url": url,
        "call_started": False,
        "message": "Discord abierto en el canal. Inicia la llamada manualmente.",
    }
