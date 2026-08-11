"""Adapters that expose Windows Agent capabilities to the Pipα Core router."""

from __future__ import annotations

import webbrowser
from typing import Any

from backend.pipa_core.tools import ToolCatalog, ToolDefinition
from tools.apps import open_app
from tools.audio import get_volume, mute, set_volume, unmute
from tools.commands import build_apple_music_search_url, build_web_search_url, open_codex
from tools.discord import build_discord_channel_url
from tools.league import with_client
from tools.media import send_media_action
from tools.system import get_system_status, lock_pc
from tools.timers import TimerManager
from tools.urls import validate_external_url
from tools.whatsapp import build_whatsapp_compose_url


def _text(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} debe ser texto no vacío")
    return value.strip()


def _unsafe_summary(label: str):
    return lambda _arguments: label


def build_agent_catalog(timer_manager: TimerManager) -> ToolCatalog:
    def web_search(arguments):
        url = build_web_search_url(_text(arguments, "query"))
        webbrowser.open(url)
        return {"success": True, "url": url}

    def music_search(arguments):
        url = build_apple_music_search_url(_text(arguments, "term"))
        webbrowser.open(url)
        return {"success": True, "url": url}

    def discord_open(arguments):
        channel_id = _text(arguments, "channel_id")
        guild_id = arguments.get("guild_id")
        if guild_id is not None and not isinstance(guild_id, str):
            raise ValueError("guild_id debe ser texto")
        url = build_discord_channel_url(channel_id, guild_id)
        webbrowser.open(url)
        return {"success": True, "url": url, "call_started": False}

    def whatsapp_compose(arguments):
        phone = _text(arguments, "phone")
        message = _text(arguments, "message")
        url = build_whatsapp_compose_url(phone, message)
        webbrowser.open(url)
        return {"success": True, "url": url, "sent": False}

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

    def league_search(arguments):
        return with_client(lambda client: client.start_search(_text(arguments, "queue")))

    return ToolCatalog(
        [
            ToolDefinition("system_status", lambda _args: get_system_status()),
            ToolDefinition("audio_volume", audio_volume),
            ToolDefinition("audio_mute", lambda _args: mute()),
            ToolDefinition("audio_unmute", lambda _args: unmute()),
            ToolDefinition("media_action", lambda args: send_media_action(_text(args, "action"))),
            ToolDefinition(
                "open_app",
                lambda args: open_app(_text(args, "app")),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir una aplicación en Windows"),
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
                confirm_summary=_unsafe_summary("Abrir una búsqueda en Internet"),
            ),
            ToolDefinition(
                "music_search",
                music_search,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir una búsqueda de música"),
            ),
            ToolDefinition(
                "discord_open",
                discord_open,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir un canal de Discord"),
            ),
            ToolDefinition(
                "whatsapp_compose",
                whatsapp_compose,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir WhatsApp con un mensaje preparado"),
            ),
            ToolDefinition(
                "league_search",
                league_search,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Buscar partida en League of Legends"),
            ),
            ToolDefinition(
                "system_lock",
                lambda _args: lock_pc(),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Bloquear el ordenador"),
            ),
            ToolDefinition("timer_create", timer_create),
            ToolDefinition(
                "open_url",
                lambda args: _open_url(_text(args, "url")),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir una URL externa"),
            ),
        ]
    )


def _open_url(value: str) -> dict[str, object]:
    url = validate_external_url(value)
    webbrowser.open(url)
    return {"success": True, "url": url}
