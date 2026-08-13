"""Adapters that expose Windows Agent capabilities to the Pipα Core router."""

from __future__ import annotations

import webbrowser
from typing import Any

from backend.pipa_core.tools import ToolCatalog, ToolDefinition
from tools.apps import open_app
from tools.audio import mute, set_volume, unmute
from tools.browser import open_validated_url, without_destination
from tools.capabilities import get_integration_capabilities
from tools.commands import (
    open_apple_music,
    open_apple_music_search,
    open_codex,
    open_league,
    open_web_search,
)
from tools.contacts import resolve_discord_contact, resolve_whatsapp_contact
from tools.discord import open_discord_app, open_discord_call, open_discord_channel
from tools.league import with_client, with_client_or_launch
from tools.media import send_media_action
from tools.system import get_network_status, get_power_status, get_system_status, lock_pc
from tools.timers import TimerManager, validate_timer_id
from tools.urls import validate_external_url
from tools.whatsapp import open_whatsapp_chat, open_whatsapp_compose, open_whatsapp_web


def _text(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} debe ser texto no vacío")
    return value.strip()


def _unsafe_summary(label: str):
    return lambda _arguments: label


def _value_summary(prefix: str, arguments: dict[str, Any], name: str, *, limit: int = 96) -> str:
    value = _text(arguments, name)
    compact = " ".join(value.split())
    if len(compact) > limit:
        compact = compact[: limit - 1].rstrip() + "…"
    return f"{prefix}: {compact}"


def _discord_summary(arguments: dict[str, Any]) -> str:
    channel_id = _text(arguments, "channel_id")
    guild_id = arguments.get("guild_id")
    if isinstance(guild_id, str) and guild_id.strip():
        return f"Abrir Discord: canal {channel_id} del servidor {guild_id.strip()}"
    return f"Abrir Discord: canal o DM {channel_id}"


def build_agent_catalog(timer_manager: TimerManager) -> ToolCatalog:
    def web_search(arguments):
        return open_web_search(_text(arguments, "query"))

    def music_search(arguments):
        return open_apple_music_search(_text(arguments, "term"))

    def discord_open(arguments):
        channel_id = _text(arguments, "channel_id")
        guild_id = arguments.get("guild_id")
        if guild_id is not None and not isinstance(guild_id, str):
            raise ValueError("guild_id debe ser texto")
        return open_discord_channel(channel_id, guild_id)

    def whatsapp_compose(arguments):
        phone = _text(arguments, "phone")
        message = _text(arguments, "message")
        return open_whatsapp_compose(phone, message)

    def whatsapp_contact(arguments):
        contact = _text(arguments, "contact")
        message = _text(arguments, "message")
        contact_name, phone = resolve_whatsapp_contact(contact)
        return open_whatsapp_compose(phone, message) | {"contact": contact_name}

    def whatsapp_contact_open(arguments):
        contact = _text(arguments, "contact")
        contact_name, phone = resolve_whatsapp_contact(contact)
        return open_whatsapp_chat(phone) | {"contact": contact_name}

    def audio_volume(arguments):
        percent = arguments.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, int):
            raise ValueError("percent debe ser entero")
        return set_volume(percent)

    def timer_create(arguments):
        seconds = arguments.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise ValueError("seconds debe ser entero")
        label = arguments.get("label", "Pipα timer")
        if not isinstance(label, str):
            raise ValueError("label debe ser texto")
        return timer_manager.create(seconds, label)

    def timer_cancel(arguments):
        return timer_manager.cancel(validate_timer_id(_text(arguments, "timer_id")))

    def league_search(arguments):
        queue = _text(arguments, "queue")
        return with_client_or_launch(
            lambda client: client.start_search(queue),
            open_league,
        )

    def league_cancel(_arguments):
        return with_client(lambda client: client.cancel_search())

    def league_status(_arguments):
        return with_client(lambda client: client.status())

    def league_search_status(_arguments):
        return with_client(lambda client: client.search_status())

    def music_open(_arguments):
        return without_destination(open_apple_music())

    def discord_open_app(_arguments):
        return without_destination(open_discord_app())

    def discord_contact(arguments):
        contact = _text(arguments, "contact")
        contact_name, channel_id, guild_id = resolve_discord_contact(contact)
        return open_discord_channel(channel_id, guild_id) | {"contact": contact_name}

    def discord_call(arguments):
        contact = _text(arguments, "contact")
        contact_name, channel_id, guild_id = resolve_discord_contact(contact)
        return open_discord_call(channel_id, guild_id) | {"contact": contact_name}

    def whatsapp_open(_arguments):
        return without_destination(open_whatsapp_web())

    return ToolCatalog(
        [
            ToolDefinition("system_status", lambda _args: get_system_status()),
            ToolDefinition("integration_status", lambda _args: get_integration_capabilities()),
            ToolDefinition("system_power", lambda _args: get_power_status()),
            ToolDefinition("system_network", lambda _args: get_network_status()),
            ToolDefinition("audio_volume", audio_volume),
            ToolDefinition("audio_mute", lambda _args: mute()),
            ToolDefinition("audio_unmute", lambda _args: unmute()),
            ToolDefinition("media_action", lambda args: send_media_action(_text(args, "action"))),
            ToolDefinition(
                "open_app",
                lambda args: open_app(_text(args, "app")),
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Abrir aplicación", args, "app"),
            ),
            ToolDefinition(
                "open_codex",
                lambda _args: open_codex(),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir Codex"),
            ),
            ToolDefinition(
                "web_search",
                web_search,
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Buscar en Internet", args, "query"),
            ),
            ToolDefinition(
                "music_search",
                music_search,
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Buscar en Apple Music", args, "term"),
            ),
            ToolDefinition(
                "music_open",
                music_open,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir Apple Music"),
            ),
            ToolDefinition(
                "league_open",
                lambda _args: open_league(),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir League of Legends"),
            ),
            ToolDefinition(
                "discord_open_app",
                discord_open_app,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir Discord"),
            ),
            ToolDefinition(
                "discord_open",
                discord_open,
                safety="unsafe",
                confirm_summary=_discord_summary,
            ),
            ToolDefinition(
                "discord_contact",
                discord_contact,
                safety="unsafe",
                confirm_summary=lambda args: f"Abrir Discord para contacto {_text(args, 'contact')}",
            ),
            ToolDefinition(
                "discord_call",
                discord_call,
                safety="unsafe",
                confirm_summary=lambda args: (
                    f"Abrir llamada de Discord para contacto {_text(args, 'contact')}; "
                    "la llamada se inicia manualmente"
                ),
            ),
            ToolDefinition(
                "whatsapp_compose",
                whatsapp_compose,
                safety="unsafe",
                confirm_summary=lambda args: (
                    f"Preparar WhatsApp para {_text(args, 'phone')}: "
                    f"{' '.join(_text(args, 'message').split())[:72]}"
                ),
            ),
            ToolDefinition(
                "whatsapp_contact",
                whatsapp_contact,
                safety="unsafe",
                confirm_summary=lambda args: (
                    f"Preparar WhatsApp para contacto {_text(args, 'contact')}: "
                    f"{' '.join(_text(args, 'message').split())[:72]}"
                ),
            ),
            ToolDefinition(
                "whatsapp_contact_open",
                whatsapp_contact_open,
                safety="unsafe",
                confirm_summary=lambda args: f"Abrir WhatsApp para contacto {_text(args, 'contact')}",
            ),
            ToolDefinition(
                "whatsapp_open",
                whatsapp_open,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir WhatsApp Web"),
            ),
            ToolDefinition(
                "league_search",
                league_search,
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Buscar partida", args, "queue"),
            ),
            ToolDefinition("league_status", league_status),
            ToolDefinition("league_search_status", league_search_status),
            ToolDefinition(
                "league_cancel",
                league_cancel,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Cancelar la búsqueda de League of Legends"),
            ),
            ToolDefinition(
                "system_lock",
                lambda _args: lock_pc(),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Bloquear el ordenador"),
            ),
            ToolDefinition("timer_create", timer_create),
            ToolDefinition("timer_list", lambda _args: {"timers": timer_manager.list()}),
            ToolDefinition("timer_cancel", timer_cancel),
            ToolDefinition(
                "open_url",
                lambda args: _open_url(_text(args, "url")),
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Abrir URL", args, "url", limit=120),
            ),
        ]
    )


def _open_url(value: str) -> dict[str, object]:
    url = validate_external_url(value)
    return without_destination(
        open_validated_url(
            url,
            browser_open=webbrowser.open,
            success_message="URL abierta en el navegador.",
            failure_message="No he podido abrir la URL en el navegador.",
        )
    )
