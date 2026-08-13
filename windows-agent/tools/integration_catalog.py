"""Non-sensitive catalog shared by local UIs and future device clients.

The catalog describes what Pipa can request; it does not grant permission to
execute anything. Every outward-facing integration remains confirmation-gated
by the Core and the actual adapter still validates its own arguments.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.league import QUEUE_IDS


def _parameter(
    name: str,
    label: str,
    kind: str,
    max_length: int,
    *,
    options: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Describe a bounded, non-sensitive input for a structured client."""

    value: dict[str, Any] = {
        "name": name,
        "label": label,
        "kind": kind,
        "max_length": max_length,
    }
    if options:
        value["options"] = list(options)
    return value


def build_integration_capabilities(
    *,
    apple_music_configured: bool,
    league_available: bool,
    league_ready: bool,
    codex_configured: bool,
    whatsapp_app_configured: bool = False,
    discord_app_configured: bool = False,
    whatsapp_contacts_configured: bool = False,
    discord_contacts_configured: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build the stable feature matrix without exposing local configuration."""

    return {
        "web_search": {
            "available": True,
            "requires_confirmation": True,
            "execution": "opens_browser",
        },
        "apple_music": {
            "available": True,
            "app_configured": apple_music_configured,
            "search": True,
            "playback": False,
            "media_control": True,
            "requires_manual_selection": True,
            "requires_confirmation": True,
        },
        "whatsapp": {
            "available": True,
            "app_configured": whatsapp_app_configured,
            "open_web": True,
            "open_contact": True,
            "contact_aliases_configured": whatsapp_contacts_configured,
            "prepare_message": True,
            "send_message": False,
            "requires_manual_send": True,
            "requires_confirmation": True,
        },
        "discord": {
            "available": True,
            "app_configured": discord_app_configured,
            "open_app": True,
            "open_channel": True,
            "contact_aliases_configured": discord_contacts_configured,
            "start_call": False,
            "requires_manual_call": True,
            "requires_confirmation": True,
        },
        "league": {
            "available": league_available,
            "client_ready": league_ready,
            "open_client": league_available,
            "matchmaking": league_available,
            "cancel_matchmaking": league_ready,
            "queues": sorted(QUEUE_IDS),
            "requires_confirmation": True,
        },
        "codex": {
            "available": codex_configured,
            "open_app": codex_configured,
            "writes_to_chat": False,
            "requires_confirmation": True,
        },
    }


_COMMANDS: tuple[dict[str, Any], ...] = (
    {
        "id": "system_status",
        "tool_name": "system_status",
        "phrase": "estado del ordenador",
        "description": "Consulta un estado resumido del ordenador.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "integration_status",
        "tool_name": "integration_status",
        "phrase": "estado de integraciones",
        "description": "Consulta qué integraciones están configuradas, sin ejecutar ninguna acción.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "web_search",
        "tool_name": "web_search",
        "phrase": "busca en internet <consulta>",
        "description": "Abre una búsqueda en el navegador.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("query", "Consulta", "text", 200)],
    },
    {
        "id": "open_app",
        "tool_name": "open_app",
        "phrase": "abre una aplicación configurada <nombre>",
        "description": "Abre una aplicación previamente configurada en el PC.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("app", "Aplicación", "app", 80)],
    },
    {
        "id": "open_codex",
        "tool_name": "open_codex",
        "phrase": "abre Codex",
        "description": "Abre Codex sin escribir ni enviar mensajes.",
        "safety": "unsafe",
        "requires_confirmation": True,
    },
    {
        "id": "music_open",
        "tool_name": "music_open",
        "phrase": "abre Apple Music",
        "description": "Abre Apple Music o su catálogo web.",
        "safety": "unsafe",
        "requires_confirmation": True,
    },
    {
        "id": "music_search",
        "tool_name": "music_search",
        "phrase": "busca en Apple Music <artista o canción>",
        "description": "Abre los resultados; la pista se elige y reproduce manualmente.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("term", "Artista o canción", "text", 200)],
    },
    {
        "id": "whatsapp_compose",
        "tool_name": "whatsapp_compose",
        "phrase": "prepara WhatsApp para <teléfono> y dile <mensaje>",
        "description": "Abre el chat con el texto preparado; nunca pulsa Enviar.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [
            _parameter("phone", "Teléfono", "phone", 32),
            _parameter("message", "Mensaje", "message", 3800),
        ],
    },
    {
        "id": "whatsapp_open",
        "tool_name": "whatsapp_open",
        "phrase": "abre WhatsApp",
        "description": "Abre WhatsApp Web sin enviar mensajes.",
        "safety": "unsafe",
        "requires_confirmation": True,
    },
    {
        "id": "whatsapp_contact",
        "tool_name": "whatsapp_contact",
        "phrase": "prepara WhatsApp para <contacto> y dile <mensaje>",
        "description": "Usa un alias local, abre el chat y deja el envío para la persona.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [
            _parameter("contact", "Contacto", "contact", 80),
            _parameter("message", "Mensaje", "message", 3800),
        ],
    },
    {
        "id": "whatsapp_contact_open",
        "tool_name": "whatsapp_contact_open",
        "phrase": "abre WhatsApp para <contacto>",
        "description": "Abre el chat de un alias local sin preparar ni enviar mensajes.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("contact", "Contacto", "contact", 80)],
    },
    {
        "id": "whatsapp_phone_open",
        "tool_name": "whatsapp_phone_open",
        "phrase": "abre WhatsApp para <teléfono>",
        "description": "Abre un chat por teléfono sin preparar ni enviar mensajes.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("phone", "Teléfono", "phone", 32)],
    },
    {
        "id": "discord_open_app",
        "tool_name": "discord_open_app",
        "phrase": "abre Discord",
        "description": "Abre Discord sin iniciar llamadas.",
        "safety": "unsafe",
        "requires_confirmation": True,
    },
    {
        "id": "discord_open",
        "tool_name": "discord_open",
        "phrase": "abre Discord canal <id>",
        "description": "Abre un canal o DM; nunca inicia una llamada.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("channel_id", "ID del canal", "channel_id", 20)],
    },
    {
        "id": "discord_server_channel",
        "tool_name": "discord_open",
        "phrase": "abre Discord servidor <servidor> canal <canal>",
        "description": "Abre un canal de servidor; nunca inicia una llamada.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [
            _parameter("guild_id", "ID del servidor", "guild_id", 20),
            _parameter("channel_id", "ID del canal", "channel_id", 20),
        ],
    },
    {
        "id": "discord_contact",
        "tool_name": "discord_contact",
        "phrase": "abre el canal de <contacto> en Discord",
        "description": "Usa un alias local, abre el canal y deja la llamada para la persona.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("contact", "Contacto", "contact", 80)],
    },
    {
        "id": "discord_call_channel",
        "tool_name": "discord_call_channel",
        "phrase": "llama a Discord canal <id>",
        "description": "Abre el destino de llamada; pulsa Llamar manualmente.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("channel_id", "ID del canal", "channel_id", 20)],
    },
    {
        "id": "discord_call_server_channel",
        "tool_name": "discord_call_channel",
        "phrase": "llama a Discord servidor <servidor> canal <canal>",
        "description": "Abre el destino de llamada; pulsa Llamar manualmente.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [
            _parameter("guild_id", "ID del servidor", "guild_id", 20),
            _parameter("channel_id", "ID del canal", "channel_id", 20),
        ],
    },
    {
        "id": "discord_call",
        "tool_name": "discord_call",
        "phrase": "llama a <contacto> en Discord",
        "description": "Abre el destino de llamada; la persona pulsa Llamar manualmente.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("contact", "Contacto", "contact", 80)],
    },
    {
        "id": "league_open",
        "tool_name": "league_open",
        "phrase": "abre League of Legends",
        "description": "Abre el cliente de League sin iniciar una partida.",
        "safety": "unsafe",
        "requires_confirmation": True,
    },
    {
        "id": "league_search",
        "tool_name": "league_search",
        "phrase": "busca una partida <cola>",
        "description": "Inicia matchmaking en una cola allowlisted; abre League si aún no está listo.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [
            _parameter(
                "queue",
                "Cola",
                "queue",
                32,
                options=tuple(sorted(QUEUE_IDS)),
            )
        ],
    },
    {
        "id": "league_status",
        "tool_name": "league_status",
        "phrase": "estado de League",
        "description": "Consulta lobby y matchmaking sin iniciar ninguna acción.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "league_search_status",
        "tool_name": "league_search_status",
        "phrase": "estado de búsqueda de League",
        "description": "Consulta solo si el cliente está buscando partida.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "league_cancel",
        "tool_name": "league_cancel",
        "phrase": "cancela la búsqueda de League",
        "description": "Cancela la búsqueda activa del cliente local.",
        "safety": "unsafe",
        "requires_confirmation": True,
    },
    {
        "id": "audio_volume",
        "tool_name": "audio_volume",
        "phrase": "pon el volumen <0-100>",
        "description": "Ajusta el volumen del ordenador.",
        "safety": "safe",
        "requires_confirmation": False,
        "parameters": [_parameter("percent", "Volumen (0-100)", "integer", 3)],
    },
    {
        "id": "system_power",
        "tool_name": "system_power",
        "phrase": "estado de batería",
        "description": "Consulta batería y alimentación del ordenador.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "system_network",
        "tool_name": "system_network",
        "phrase": "estado de red",
        "description": "Consulta el estado resumido de las interfaces de red.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "audio_mute",
        "tool_name": "audio_mute",
        "phrase": "silencia el ordenador",
        "description": "Silencia el audio del ordenador.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "audio_unmute",
        "tool_name": "audio_unmute",
        "phrase": "activa el sonido",
        "description": "Activa el audio del ordenador.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "media_action",
        "tool_name": "media_action",
        "phrase": "control multimedia <acción>",
        "description": "Envía una tecla multimedia allowlisted.",
        "safety": "safe",
        "requires_confirmation": False,
        "parameters": [
            _parameter(
                "action",
                "Acción",
                "action",
                16,
                options=("play_pause", "next", "previous", "stop"),
            )
        ],
    },
    {
        "id": "media_play_pause",
        "tool_name": "media_action",
        "default_arguments": {"action": "play_pause"},
        "phrase": "reproduce la canción seleccionada",
        "description": "Reproduce o pausa el reproductor multimedia activo; no elige una pista.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "media_next",
        "tool_name": "media_action",
        "default_arguments": {"action": "next"},
        "phrase": "siguiente canción",
        "description": "Pasa a la siguiente pista del reproductor multimedia activo.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "media_previous",
        "tool_name": "media_action",
        "default_arguments": {"action": "previous"},
        "phrase": "canción anterior",
        "description": "Vuelve a la pista anterior del reproductor multimedia activo.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "media_stop",
        "tool_name": "media_action",
        "default_arguments": {"action": "stop"},
        "phrase": "detén la música",
        "description": "Detiene el reproductor multimedia activo.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "timer_create",
        "tool_name": "timer_create",
        "phrase": "crea un temporizador <segundos>",
        "description": "Crea un temporizador local en memoria.",
        "safety": "safe",
        "requires_confirmation": False,
        "parameters": [_parameter("seconds", "Segundos", "integer", 6)],
    },
    {
        "id": "timer_list",
        "tool_name": "timer_list",
        "phrase": "lista los temporizadores",
        "description": "Consulta los temporizadores locales activos.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "timer_cancel",
        "tool_name": "timer_cancel",
        "phrase": "cancela el temporizador <id>",
        "description": "Cancela un temporizador local por su identificador.",
        "safety": "safe",
        "requires_confirmation": False,
        "parameters": [_parameter("timer_id", "ID del temporizador", "text", 32)],
    },
    {
        "id": "system_lock",
        "tool_name": "system_lock",
        "phrase": "bloquea el ordenador",
        "description": "Bloquea Windows y requiere confirmación.",
        "safety": "unsafe",
        "requires_confirmation": True,
    },
    {
        "id": "open_url",
        "tool_name": "open_url",
        "phrase": "abre una URL validada <dirección>",
        "description": "Abre una URL HTTP(S) validada en el navegador.",
        "safety": "unsafe",
        "requires_confirmation": True,
        "parameters": [_parameter("url", "Dirección", "url", 2048)],
    },
)


def get_command_catalog() -> list[dict[str, Any]]:
    """Return fresh JSON-safe command descriptors for a local UI."""

    commands = [deepcopy(command) for command in _COMMANDS]
    # An explicit empty list advertises that a no-argument action supports
    # the structured tool path. Older agents that omit this field still use
    # the text-editor fallback in compatible clients.
    for command in commands:
        command.setdefault("parameters", [])
    return commands
