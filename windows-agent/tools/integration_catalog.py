"""Non-sensitive catalog shared by local UIs and future device clients.

The catalog describes what Pipa can request; it does not grant permission to
execute anything. Every outward-facing integration remains confirmation-gated
by the Core and the actual adapter still validates its own arguments.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from tools.league import QUEUE_IDS
from tools.text_policy import validate_bounded_text

_MAX_COMMANDS = 64
_MAX_PARAMETERS = 8
_MAX_PARAMETER_OPTIONS = 16
_MAX_COMMAND_TEXT_BYTES = 256
_MAX_PARAMETER_TEXT_BYTES = 128
_COMMAND_FIELDS = frozenset(
    {
        "id",
        "tool_name",
        "phrase",
        "description",
        "safety",
        "requires_confirmation",
        "parameters",
        "default_arguments",
    }
)
_PARAMETER_FIELDS = frozenset({"name", "label", "kind", "max_length", "options"})
_PARAMETER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_PHRASE_PLACEHOLDER = re.compile(r"<([^<>]+)>")
_PARAMETER_KINDS = frozenset(
    {
        "text",
        "message",
        "phone",
        "integer",
        "queue",
        "action",
        "app",
        "contact",
        "channel_id",
        "guild_id",
        "url",
    }
)

# These are safety properties, not availability flags.  Availability changes
# with local configuration; crossing one of these boundaries would change
# what a remote UI is allowed to believe the agent can do.  Keep the contract
# next to the capability builder so a new integration cannot silently drift
# from the public policy used by diagnostics and mobile clients.
_INTEGRATION_SAFETY_CONTRACT: dict[str, dict[str, bool]] = {
    "web_search": {
        "requires_confirmation": True,
    },
    "apple_music": {
        "playback": False,
        "media_control": True,
        "requires_manual_selection": True,
        "requires_confirmation": True,
    },
    "whatsapp": {
        "send_message": False,
        "requires_manual_send": True,
        "requires_confirmation": True,
    },
    "discord": {
        "start_call": False,
        "requires_manual_call": True,
        "requires_confirmation": True,
    },
    "league": {
        "accept_match": False,
        "requires_manual_accept": True,
        "requires_confirmation": True,
    },
    "codex": {
        "writes_to_chat": False,
        "requires_confirmation": True,
    },
}


def validate_integration_capabilities(capabilities: object) -> None:
    """Fail closed if the public integration matrix crosses a safety boundary."""

    if not isinstance(capabilities, dict):
        raise ValueError("integration capabilities must be an object")
    unknown_integrations = set(capabilities) - set(_INTEGRATION_SAFETY_CONTRACT)
    if unknown_integrations:
        names = ", ".join(sorted(str(name) for name in unknown_integrations))
        raise ValueError(f"integrations without a safety contract: {names}")
    for integration, expected_fields in _INTEGRATION_SAFETY_CONTRACT.items():
        values = capabilities.get(integration)
        if not isinstance(values, dict):
            raise ValueError(f"missing integration capability: {integration}")
        for field, expected in expected_fields.items():
            if type(values.get(field)) is not bool or values[field] is not expected:
                raise ValueError(f"{integration}.{field} crosses the integration safety contract")


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
    apple_music_launcher_resolved: bool | None = None,
    league_available: bool,
    league_launcher_resolved: bool | None = None,
    league_ready: bool,
    codex_configured: bool,
    codex_launcher_resolved: bool | None = None,
    whatsapp_app_configured: bool = False,
    whatsapp_launcher_resolved: bool | None = None,
    discord_app_configured: bool = False,
    discord_launcher_resolved: bool | None = None,
    whatsapp_contacts_configured: bool = False,
    discord_contacts_configured: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build the stable feature matrix without exposing local configuration."""

    def launcher_state(configured: bool, resolved: bool | None) -> bool:
        """Keep readiness false when no corresponding app is configured."""

        return configured and (configured if resolved is None else resolved)

    capabilities = {
        "web_search": {
            "available": True,
            "requires_confirmation": True,
            "execution": "opens_browser",
        },
        "apple_music": {
            "available": True,
            "app_configured": apple_music_configured,
            "launcher_resolved": launcher_state(apple_music_configured, apple_music_launcher_resolved),
            "search": True,
            "playback": False,
            "media_control": True,
            "requires_manual_selection": True,
            "requires_confirmation": True,
        },
        "whatsapp": {
            "available": True,
            "app_configured": whatsapp_app_configured,
            "launcher_resolved": launcher_state(whatsapp_app_configured, whatsapp_launcher_resolved),
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
            "launcher_resolved": launcher_state(discord_app_configured, discord_launcher_resolved),
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
            "launcher_resolved": launcher_state(league_available, league_launcher_resolved),
            "open_client": league_available,
            "matchmaking": league_available,
            "cancel_matchmaking": league_ready,
            "accept_match": False,
            "requires_manual_accept": True,
            "queues": sorted(QUEUE_IDS),
            "requires_confirmation": True,
        },
        "codex": {
            "available": codex_configured,
            "open_app": codex_configured,
            "launcher_resolved": launcher_state(codex_configured, codex_launcher_resolved),
            "writes_to_chat": False,
            "requires_confirmation": True,
        },
    }
    validate_integration_capabilities(capabilities)
    return capabilities


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
        "description": "Consulta si busca partida o si hay una pendiente de aceptación manual.",
        "safety": "safe",
        "requires_confirmation": False,
    },
    {
        "id": "league_wait",
        "tool_name": "league_wait",
        "phrase": "espera a que League encuentre una partida <segundos>",
        "description": "Observa matchmaking durante un tiempo limitado; la aceptación sigue siendo manual.",
        "safety": "safe",
        "requires_confirmation": False,
        "parameters": [_parameter("seconds", "Segundos", "integer", 3)],
    },
    {
        "id": "league_cancel",
        "tool_name": "league_cancel",
        "phrase": "cancela la búsqueda de League",
        "description": "Cancela una búsqueda confirmada; no rechaza una partida ya encontrada.",
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


def _safe_catalog_text(value: object, field_name: str, maximum_bytes: int) -> str:
    try:
        return validate_bounded_text(value, field_name, maximum_bytes)
    except ValueError as error:
        raise ValueError(f"{field_name} no es texto de catálogo válido") from error


def _validate_parameters(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_PARAMETERS:
        raise ValueError("parameters no es una lista acotada")

    validated: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for parameter in value:
        if not isinstance(parameter, dict) or set(parameter) - _PARAMETER_FIELDS:
            raise ValueError("parameter contiene campos no permitidos")
        name = parameter.get("name")
        label = parameter.get("label")
        kind = parameter.get("kind")
        max_length = parameter.get("max_length")
        if (
            not isinstance(name, str)
            or _PARAMETER_NAME.fullmatch(name) is None
            or name in seen_names
            or not isinstance(kind, str)
            or kind not in _PARAMETER_KINDS
            or isinstance(max_length, bool)
            or not isinstance(max_length, int)
            or not 1 <= max_length <= 4096
        ):
            raise ValueError("parameter no es válido")
        safe_label = _safe_catalog_text(label, "label", _MAX_PARAMETER_TEXT_BYTES)
        options = parameter.get("options", [])
        if (
            not isinstance(options, list)
            or len(options) > _MAX_PARAMETER_OPTIONS
            or not all(isinstance(option, str) for option in options)
        ):
            raise ValueError("options no es una lista válida")
        safe_options = [_safe_catalog_text(option, "option", _MAX_PARAMETER_TEXT_BYTES) for option in options]
        if len(set(safe_options)) != len(safe_options):
            raise ValueError("options no puede contener duplicados")
        validated_parameter: dict[str, Any] = {
            "name": name,
            "label": safe_label.strip(),
            "kind": kind,
            "max_length": max_length,
        }
        if safe_options:
            validated_parameter["options"] = safe_options
        validated.append(validated_parameter)
        seen_names.add(name)
    return validated


def _validate_default_arguments(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value or len(value) > _MAX_PARAMETERS:
        raise ValueError("default_arguments no es un objeto acotado")
    result: dict[str, str] = {}
    for name, argument in value.items():
        if not isinstance(name, str) or _PARAMETER_NAME.fullmatch(name) is None:
            raise ValueError("default_arguments contiene un nombre inválido")
        result[name] = _safe_catalog_text(argument, "default_argument", _MAX_PARAMETER_TEXT_BYTES).strip()
    return result


def _phrase_placeholders(phrase: str) -> list[str]:
    """Extract the bounded, visible fields used by the mobile editor."""

    placeholders = [match.strip() for match in _PHRASE_PLACEHOLDER.findall(phrase)]
    if any(not placeholder or len(placeholder.encode("utf-8")) > 80 for placeholder in placeholders) or len(
        placeholders
    ) != len(set(placeholders)):
        raise ValueError("phrase contiene marcadores inválidos o duplicados")
    return placeholders


def validate_command_catalog(commands: object) -> list[dict[str, Any]]:
    """Validate the local public catalog before exposing it to any UI."""

    if not isinstance(commands, list) or len(commands) > _MAX_COMMANDS:
        raise ValueError("command catalog is too large")
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for command in commands:
        if not isinstance(command, dict) or set(command) - _COMMAND_FIELDS:
            raise ValueError("command contains fields outside the public contract")
        command_id = _safe_catalog_text(command.get("id"), "id", _MAX_COMMAND_TEXT_BYTES).strip()
        if command_id in seen_ids:
            raise ValueError("command IDs must be unique")
        tool_name = _safe_catalog_text(command.get("tool_name"), "tool_name", _MAX_COMMAND_TEXT_BYTES).strip()
        phrase = _safe_catalog_text(command.get("phrase"), "phrase", _MAX_COMMAND_TEXT_BYTES).strip()
        description = _safe_catalog_text(
            command.get("description"), "description", _MAX_COMMAND_TEXT_BYTES
        ).strip()
        safety = command.get("safety")
        requires_confirmation = command.get("requires_confirmation")
        if safety not in {"safe", "unsafe"} or not isinstance(requires_confirmation, bool):
            raise ValueError("command safety metadata is invalid")
        if requires_confirmation != (safety == "unsafe"):
            raise ValueError("command safety metadata is inconsistent")
        parameters = _validate_parameters(command.get("parameters", []))
        placeholders = _phrase_placeholders(phrase)
        if len(placeholders) != len(parameters):
            raise ValueError("phrase y parameters deben describir el mismo número de campos")
        default_arguments = None
        if "default_arguments" in command:
            default_arguments = _validate_default_arguments(command["default_arguments"])
            if parameters or placeholders:
                raise ValueError("fixed arguments cannot accompany editable parameters")
        normalized: dict[str, Any] = {
            "id": command_id,
            "tool_name": tool_name,
            "phrase": phrase,
            "description": description,
            "safety": safety,
            "requires_confirmation": requires_confirmation,
            "parameters": parameters,
        }
        if default_arguments is not None:
            normalized["default_arguments"] = default_arguments
        validated.append(normalized)
        seen_ids.add(command_id)
    return validated


def get_command_catalog() -> list[dict[str, Any]]:
    """Return fresh JSON-safe command descriptors for a local UI."""

    # An explicit empty list advertises that a no-argument action supports
    # the structured tool path. Older agents that omit this field still use
    # the text-editor fallback in compatible clients.
    commands = [deepcopy(command) for command in _COMMANDS]
    return validate_command_catalog(commands)
