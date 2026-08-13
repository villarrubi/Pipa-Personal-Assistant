"""Safe Discord navigation helpers.

The agent can open a known Discord DM or channel. It deliberately does not
automate a personal Discord account, scrape contacts, or click call buttons.
The explicit call helper only opens the destination and reports that the
human still has to press the call button.
"""

from __future__ import annotations

import re
import webbrowser

from tools.browser import open_validated_url, without_destination
from tools.urls import validate_external_url

_SNOWFLAKE = re.compile(r"^[0-9]{17,20}$")
DISCORD_APP_URL = "https://discord.com/app"


def _validate_snowflake(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SNOWFLAKE.fullmatch(value.strip()) is None:
        raise ValueError(f"{field_name} debe ser un ID de Discord válido.")
    return value.strip()


def build_discord_channel_url(channel_id: str, guild_id: str | None = None) -> str:
    """Build a Discord URL for a DM, group DM, or server channel."""
    channel = _validate_snowflake(channel_id, "channel_id")
    guild = "@me" if guild_id is None else _validate_snowflake(guild_id, "guild_id")
    return validate_external_url(f"https://discord.com/channels/{guild}/{channel}")


def build_discord_app_url() -> str:
    return validate_external_url(DISCORD_APP_URL)


def open_discord_app() -> dict[str, object]:
    """Open Discord's authenticated web app without starting a call."""

    url = build_discord_app_url()
    return without_destination(
        open_validated_url(
            url,
            browser_open=webbrowser.open,
            success_message="Discord abierto; las llamadas se inician manualmente.",
            failure_message="No he podido abrir Discord.",
        )
    ) | {"call_started": False}


def open_discord_channel(channel_id: str, guild_id: str | None = None) -> dict[str, object]:
    url = build_discord_channel_url(channel_id, guild_id)
    return without_destination(
        open_validated_url(
            url,
            browser_open=webbrowser.open,
            success_message="Discord abierto en el canal; las llamadas se inician manualmente.",
            failure_message="No he podido abrir el canal de Discord.",
        )
    ) | {"call_started": False}


def open_discord_call(channel_id: str, guild_id: str | None = None) -> dict[str, object]:
    """Open a call destination without starting the Discord call."""

    url = build_discord_channel_url(channel_id, guild_id)
    return without_destination(
        open_validated_url(
            url,
            browser_open=webbrowser.open,
            success_message="Canal de Discord abierto; pulsa Llamar manualmente.",
            failure_message="No he podido abrir el destino de llamada de Discord.",
        )
    ) | {"call_started": False, "requires_manual_call": True}
