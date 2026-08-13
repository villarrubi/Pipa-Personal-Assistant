"""Side-effect-free checks for Pipα's outward integration contracts.

The real adapters can open applications, browsers, or the local League
client. This module intentionally imports only their bounded builders and
queue/capability metadata, so diagnostics and CI never perform an external
action or read local contact configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from tools.commands import (
    build_apple_music_browse_url,
    build_apple_music_search_url,
    build_web_search_url,
)
from tools.discord import build_discord_app_url, build_discord_channel_url
from tools.integration_catalog import build_integration_capabilities
from tools.league import QUEUE_IDS, resolve_queue_id
from tools.whatsapp import (
    build_whatsapp_chat_url,
    build_whatsapp_compose_url,
    build_whatsapp_web_url,
)

_SAMPLE_PHONE = "+34600000000"
_SAMPLE_DISCORD_CHANNEL = "12345678901234567"
_SAMPLE_DISCORD_GUILD = "98765432109876543"


def _check_https_host(name: str, builder: Callable[[], str], expected_host: str) -> None:
    value = builder()
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password:
        raise ValueError(f"{name} returned an invalid public destination")


def run_integration_self_test() -> dict[str, object]:
    """Validate integration builders, queues, and manual-action boundaries.

    All input values are synthetic constants. The result deliberately contains
    counts and booleans only; it never returns a generated URL, phone number,
    Discord ID, application path, or message.
    """

    builders: tuple[tuple[str, Callable[[], str], str], ...] = (
        ("web_search", lambda: build_web_search_url("Pipa integration diagnostic"), "www.google.com"),
        (
            "apple_music_search",
            lambda: build_apple_music_search_url("Pipa integration diagnostic"),
            "music.apple.com",
        ),
        ("apple_music_browse", build_apple_music_browse_url, "music.apple.com"),
        ("whatsapp_web", build_whatsapp_web_url, "web.whatsapp.com"),
        ("whatsapp_chat", lambda: build_whatsapp_chat_url(_SAMPLE_PHONE), "wa.me"),
        (
            "whatsapp_compose",
            lambda: build_whatsapp_compose_url(_SAMPLE_PHONE, "Pipa integration diagnostic"),
            "wa.me",
        ),
        ("discord_app", build_discord_app_url, "discord.com"),
        (
            "discord_channel",
            lambda: build_discord_channel_url(_SAMPLE_DISCORD_CHANNEL, _SAMPLE_DISCORD_GUILD),
            "discord.com",
        ),
    )
    for name, builder, expected_host in builders:
        _check_https_host(name, builder, expected_host)

    for queue_name, queue_id in QUEUE_IDS.items():
        if resolve_queue_id(queue_name) != queue_id:
            raise ValueError("League queue metadata is inconsistent")

    capabilities = build_integration_capabilities(
        apple_music_configured=True,
        league_available=True,
        league_ready=True,
        codex_configured=True,
        whatsapp_app_configured=True,
        discord_app_configured=True,
        whatsapp_contacts_configured=True,
        discord_contacts_configured=True,
    )
    manual_boundaries = (
        capabilities["apple_music"]["playback"] is False
        and capabilities["apple_music"]["requires_manual_selection"] is True
        and capabilities["whatsapp"]["send_message"] is False
        and capabilities["whatsapp"]["requires_manual_send"] is True
        and capabilities["discord"]["start_call"] is False
        and capabilities["discord"]["requires_manual_call"] is True
        and capabilities["league"]["accept_match"] is False
        and capabilities["league"]["requires_manual_accept"] is True
        and capabilities["codex"]["writes_to_chat"] is False
    )
    if not manual_boundaries:
        raise ValueError("an integration capability crossed its manual-action boundary")

    return {
        "url_builders_checked": len(builders),
        "league_queues_checked": len(QUEUE_IDS),
        "manual_boundaries": True,
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }
