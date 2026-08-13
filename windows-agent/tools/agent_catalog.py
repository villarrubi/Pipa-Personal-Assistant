"""Adapters that expose Windows Agent capabilities to the Pipα Core router."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from typing import Any

from backend.pipa_core.tools import ToolCatalog, ToolDefinition
from tools.apps import open_app
from tools.audio import mute, set_volume, unmute
from tools.browser import open_validated_url, without_destination
from tools.capabilities import get_integration_capabilities
from tools.commands import (
    build_apple_music_search_url,
    build_web_search_url,
    open_apple_music,
    open_apple_music_search,
    open_codex,
    open_league,
    open_web_search,
)
from tools.contacts import resolve_discord_contact, resolve_whatsapp_contact
from tools.discord import (
    build_discord_channel_url,
    open_discord_app,
    open_discord_call,
    open_discord_channel,
)
from tools.league import resolve_queue_id, with_client, with_client_or_launch
from tools.media import send_media_action
from tools.system import get_network_status, get_power_status, get_system_status, lock_pc
from tools.text_policy import validate_bounded_text
from tools.timers import MAX_TIMER_SECONDS, TimerManager, validate_timer_id
from tools.urls import validate_external_url
from tools.whatsapp import (
    build_whatsapp_compose_url,
    open_whatsapp_chat,
    open_whatsapp_compose,
    open_whatsapp_web,
)


def _text(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} debe ser texto no vacío")
    return value.strip()


def _validate_argument_text(value: Any, name: str, maximum: int, *, allow_line_feed: bool = False) -> None:
    try:
        validate_bounded_text(value, name, maximum, allow_line_feed=allow_line_feed)
    except ValueError as error:
        raise ValueError(f"{name} debe ser texto no vacío y acotado") from error


def _argument_schema(
    *,
    required_text: dict[str, int] | None = None,
    optional_text: dict[str, int] | None = None,
    required_integers: dict[str, tuple[int, int]] | None = None,
    choices: dict[str, tuple[str, ...]] | None = None,
    check: Callable[[dict[str, Any]], None] | None = None,
) -> Callable[[dict[str, Any]], None]:
    required_text = required_text or {}
    optional_text = optional_text or {}
    required_integers = required_integers or {}
    choices = choices or {}
    allowed = set(required_text) | set(optional_text) | set(required_integers) | set(choices)

    def validate(arguments: dict[str, Any]) -> None:
        unknown = set(arguments) - allowed
        missing = (set(required_text) | set(required_integers)) - set(arguments)
        if unknown or missing:
            raise ValueError("los argumentos de la herramienta no coinciden con su contrato")
        for name, maximum in required_text.items():
            _validate_argument_text(arguments[name], name, maximum, allow_line_feed=name == "message")
        for name, maximum in optional_text.items():
            if name in arguments:
                _validate_argument_text(arguments[name], name, maximum, allow_line_feed=name == "message")
        for name, bounds in required_integers.items():
            value = arguments[name]
            if type(value) is not int or not bounds[0] <= value <= bounds[1]:
                raise ValueError(f"{name} debe ser un entero dentro del rango permitido")
        for name, allowed_values in choices.items():
            if arguments.get(name) not in allowed_values:
                raise ValueError(f"{name} no es una opción permitida")
        if check is not None:
            check(arguments)

    return validate


def _no_arguments(arguments: dict[str, Any]) -> None:
    if arguments:
        raise ValueError("esta herramienta no acepta argumentos")


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
    no_arguments = _no_arguments
    web_search_arguments = _argument_schema(
        required_text={"query": 200},
        check=lambda arguments: build_web_search_url(arguments["query"]),
    )
    music_search_arguments = _argument_schema(
        required_text={"term": 200},
        check=lambda arguments: build_apple_music_search_url(arguments["term"]),
    )
    discord_open_arguments = _argument_schema(
        required_text={"channel_id": 20},
        optional_text={"guild_id": 20},
        check=lambda arguments: build_discord_channel_url(arguments["channel_id"], arguments.get("guild_id")),
    )
    whatsapp_compose_arguments = _argument_schema(
        required_text={"phone": 32, "message": 3800},
        check=lambda arguments: build_whatsapp_compose_url(arguments["phone"], arguments["message"]),
    )
    contact_message_arguments = _argument_schema(
        required_text={"contact": 80, "message": 3800},
    )
    contact_arguments = _argument_schema(required_text={"contact": 80})
    league_search_arguments = _argument_schema(
        required_text={"queue": 32},
        check=lambda arguments: resolve_queue_id(arguments["queue"]),
    )
    media_action_arguments = _argument_schema(
        required_text={"action": 16},
        choices={"action": ("play_pause", "next", "previous", "stop")},
    )
    timer_create_arguments = _argument_schema(
        required_integers={"seconds": (1, MAX_TIMER_SECONDS)},
        optional_text={"label": 120},
    )
    timer_cancel_arguments = _argument_schema(
        required_text={"timer_id": 32},
        check=lambda arguments: validate_timer_id(arguments["timer_id"]),
    )
    open_url_arguments = _argument_schema(
        required_text={"url": 2048},
        check=lambda arguments: validate_external_url(arguments["url"]),
    )
    open_app_arguments = _argument_schema(required_text={"app": 80})

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

    def discord_call_channel(arguments):
        channel_id = _text(arguments, "channel_id")
        guild_id = arguments.get("guild_id")
        if guild_id is not None and not isinstance(guild_id, str):
            raise ValueError("guild_id debe ser texto")
        return open_discord_call(channel_id, guild_id)

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
            ToolDefinition(
                "system_status", lambda _args: get_system_status(), argument_validator=no_arguments
            ),
            ToolDefinition(
                "integration_status",
                lambda _args: get_integration_capabilities(),
                argument_validator=no_arguments,
            ),
            ToolDefinition("system_power", lambda _args: get_power_status(), argument_validator=no_arguments),
            ToolDefinition(
                "system_network", lambda _args: get_network_status(), argument_validator=no_arguments
            ),
            ToolDefinition(
                "audio_volume",
                audio_volume,
                argument_validator=_argument_schema(required_integers={"percent": (0, 100)}),
            ),
            ToolDefinition("audio_mute", lambda _args: mute(), argument_validator=no_arguments),
            ToolDefinition("audio_unmute", lambda _args: unmute(), argument_validator=no_arguments),
            ToolDefinition(
                "media_action",
                lambda args: send_media_action(_text(args, "action")),
                argument_validator=media_action_arguments,
            ),
            ToolDefinition(
                "open_app",
                lambda args: open_app(_text(args, "app")),
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Abrir aplicación", args, "app"),
                argument_validator=open_app_arguments,
            ),
            ToolDefinition(
                "open_codex",
                lambda _args: open_codex(),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir Codex"),
                argument_validator=no_arguments,
            ),
            ToolDefinition(
                "web_search",
                web_search,
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Buscar en Internet", args, "query"),
                argument_validator=web_search_arguments,
            ),
            ToolDefinition(
                "music_search",
                music_search,
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Buscar en Apple Music", args, "term"),
                argument_validator=music_search_arguments,
            ),
            ToolDefinition(
                "music_open",
                music_open,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir Apple Music"),
                argument_validator=no_arguments,
            ),
            ToolDefinition(
                "league_open",
                lambda _args: open_league(),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir League of Legends"),
                argument_validator=no_arguments,
            ),
            ToolDefinition(
                "discord_open_app",
                discord_open_app,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir Discord"),
                argument_validator=no_arguments,
            ),
            ToolDefinition(
                "discord_open",
                discord_open,
                safety="unsafe",
                confirm_summary=_discord_summary,
                argument_validator=discord_open_arguments,
            ),
            ToolDefinition(
                "discord_call_channel",
                discord_call_channel,
                safety="unsafe",
                confirm_summary=lambda args: (
                    f"Preparar llamada de Discord para canal {_text(args, 'channel_id')}; "
                    "la llamada se inicia manualmente"
                ),
                argument_validator=discord_open_arguments,
            ),
            ToolDefinition(
                "discord_contact",
                discord_contact,
                safety="unsafe",
                confirm_summary=lambda args: f"Abrir Discord para contacto {_text(args, 'contact')}",
                argument_validator=contact_arguments,
            ),
            ToolDefinition(
                "discord_call",
                discord_call,
                safety="unsafe",
                confirm_summary=lambda args: (
                    f"Abrir llamada de Discord para contacto {_text(args, 'contact')}; "
                    "la llamada se inicia manualmente"
                ),
                argument_validator=contact_arguments,
            ),
            ToolDefinition(
                "whatsapp_compose",
                whatsapp_compose,
                safety="unsafe",
                confirm_summary=lambda args: (
                    f"Preparar WhatsApp para {_text(args, 'phone')}: "
                    f"{' '.join(_text(args, 'message').split())[:72]}"
                ),
                argument_validator=whatsapp_compose_arguments,
            ),
            ToolDefinition(
                "whatsapp_contact",
                whatsapp_contact,
                safety="unsafe",
                confirm_summary=lambda args: (
                    f"Preparar WhatsApp para contacto {_text(args, 'contact')}: "
                    f"{' '.join(_text(args, 'message').split())[:72]}"
                ),
                argument_validator=contact_message_arguments,
            ),
            ToolDefinition(
                "whatsapp_contact_open",
                whatsapp_contact_open,
                safety="unsafe",
                confirm_summary=lambda args: f"Abrir WhatsApp para contacto {_text(args, 'contact')}",
                argument_validator=contact_arguments,
            ),
            ToolDefinition(
                "whatsapp_open",
                whatsapp_open,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Abrir WhatsApp Web"),
                argument_validator=no_arguments,
            ),
            ToolDefinition(
                "league_search",
                league_search,
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Buscar partida", args, "queue"),
                argument_validator=league_search_arguments,
            ),
            ToolDefinition("league_status", league_status, argument_validator=no_arguments),
            ToolDefinition("league_search_status", league_search_status, argument_validator=no_arguments),
            ToolDefinition(
                "league_cancel",
                league_cancel,
                safety="unsafe",
                confirm_summary=_unsafe_summary("Cancelar la búsqueda de League of Legends"),
                argument_validator=no_arguments,
            ),
            ToolDefinition(
                "system_lock",
                lambda _args: lock_pc(),
                safety="unsafe",
                confirm_summary=_unsafe_summary("Bloquear el ordenador"),
                argument_validator=no_arguments,
            ),
            ToolDefinition("timer_create", timer_create, argument_validator=timer_create_arguments),
            ToolDefinition(
                "timer_list", lambda _args: {"timers": timer_manager.list()}, argument_validator=no_arguments
            ),
            ToolDefinition("timer_cancel", timer_cancel, argument_validator=timer_cancel_arguments),
            ToolDefinition(
                "open_url",
                lambda args: _open_url(_text(args, "url")),
                safety="unsafe",
                confirm_summary=lambda args: _value_summary("Abrir URL", args, "url", limit=120),
                argument_validator=open_url_arguments,
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
