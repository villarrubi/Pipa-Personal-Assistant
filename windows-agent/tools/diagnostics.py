"""Read-only diagnostics for integrations and the optional device gateway.

The self-test validates configuration and bounded URL/queue builders without
opening applications, contacting League Client, or handling user data. It is
intended for installation checks and for a future device dashboard.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.pipa_core.intents import parse_text_intent
from tools.agent_catalog import build_agent_catalog
from tools.apps import AppsConfigError, load_apps
from tools.capabilities import get_capabilities
from tools.commands import (
    build_apple_music_browse_url,
    build_apple_music_search_url,
    build_web_search_url,
)
from tools.contacts import ContactsConfigError, load_contacts
from tools.discord import build_discord_app_url, build_discord_channel_url
from tools.integration_catalog import get_command_catalog
from tools.league import QUEUE_IDS, LeagueClientError, find_client_connection, resolve_queue_id
from tools.secure_diagnostics import (
    run_device_protocol_self_test,
    run_mobile_protocol_self_test,
    run_secure_self_test,
    run_secure_serial_self_test,
)
from tools.security_policy import CONFIRMATION_TOOL_PATHS, LOCAL_CONFIRMATION_PATHS
from tools.timers import TimerManager
from tools.whatsapp import build_whatsapp_chat_url, build_whatsapp_compose_url, build_whatsapp_web_url

_SAMPLE_DISCORD_CHANNEL = "12345678901234567"
_SAMPLE_DISCORD_GUILD = "98765432109876543"
_SAMPLE_PHONE = "+34600000000"
_COMMAND_ROUTE_CASES = (
    ("estado del ordenador", "system_status", {}),
    ("estado de integraciones", "integration_status", {}),
    ("estado de batería", "system_power", {}),
    ("estado de red", "system_network", {}),
    ("silencia el ordenador", "audio_mute", {}),
    ("activa el sonido", "audio_unmute", {}),
    ("pon el volumen 40", "audio_volume", {"percent": 40}),
    ("bloquea el ordenador", "system_lock", {}),
    ("busca en internet noticias de Pipa", "web_search", {"query": "noticias de Pipa"}),
    ("busca noticias de Pipa en internet", "web_search", {"query": "noticias de Pipa"}),
    ("abre Apple Music", "music_open", {}),
    ("abre Codex", "open_codex", {}),
    ("abre la aplicación calculadora", "open_app", {"app": "calculadora"}),
    ("busca en Apple Music Daft Punk", "music_search", {"term": "Daft Punk"}),
    (
        "busca una cancion de Daft Punk en Apple Music",
        "music_search",
        {"term": "Daft Punk"},
    ),
    ("busca música de Daft Punk", "music_search", {"term": "Daft Punk"}),
    ("pon música de Daft Punk en Apple Music", "music_search", {"term": "Daft Punk"}),
    ("reproduce la canción Daft Punk en Apple Music", "music_search", {"term": "Daft Punk"}),
    ("reproduce la canción seleccionada", "media_action", {"action": "play_pause"}),
    ("reanuda la pista", "media_action", {"action": "play_pause"}),
    ("detén la música", "media_action", {"action": "stop"}),
    ("siguiente canción", "media_action", {"action": "next"}),
    ("canción anterior", "media_action", {"action": "previous"}),
    ("abre WhatsApp", "whatsapp_open", {}),
    (
        "prepara WhatsApp para +34 600 123 456 y dile Hola",
        "whatsapp_compose",
        {"phone": "+34 600 123 456", "message": "Hola"},
    ),
    (
        "manda un mensaje a +34 600 123 456 por WhatsApp y dile Hola",
        "whatsapp_compose",
        {"phone": "+34 600 123 456", "message": "Hola"},
    ),
    (
        "prepara WhatsApp para mama y dile Hola",
        "whatsapp_contact",
        {"contact": "mama", "message": "Hola"},
    ),
    (
        "manda un mensaje a mama por WhatsApp y dile Hola",
        "whatsapp_contact",
        {"contact": "mama", "message": "Hola"},
    ),
    (
        "abre WhatsApp con mama y escribe Hola",
        "whatsapp_contact",
        {"contact": "mama", "message": "Hola"},
    ),
    (
        "escribe a mama por WhatsApp y dile Hola",
        "whatsapp_contact",
        {"contact": "mama", "message": "Hola"},
    ),
    (
        "abre WhatsApp para mama y dile Hola",
        "whatsapp_contact",
        {"contact": "mama", "message": "Hola"},
    ),
    ("abre WhatsApp para mama", "whatsapp_contact_open", {"contact": "mama"}),
    ("abre el chat de mama en WhatsApp", "whatsapp_contact_open", {"contact": "mama"}),
    ("abre Discord", "discord_open_app", {}),
    ("abre Discord canal 12345678901234567", "discord_open", {"channel_id": "12345678901234567"}),
    (
        "abre Discord servidor 98765432109876543 canal 12345678901234567",
        "discord_open",
        {"guild_id": "98765432109876543", "channel_id": "12345678901234567"},
    ),
    ("abre el canal de amigo en Discord", "discord_contact", {"contact": "amigo"}),
    ("abre el chat de amigo en Discord", "discord_contact", {"contact": "amigo"}),
    ("llama a amigo por Discord", "discord_call", {"contact": "amigo"}),
    ("haz una llamada a amigo por Discord", "discord_call", {"contact": "amigo"}),
    (
        "llama a Discord canal 12345678901234567",
        "discord_call_channel",
        {"channel_id": "12345678901234567"},
    ),
    (
        "llama a Discord servidor 98765432109876543 canal 12345678901234567",
        "discord_call_channel",
        {"guild_id": "98765432109876543", "channel_id": "12345678901234567"},
    ),
    ("abre LoL", "league_open", {}),
    ("busca partida solo", "league_search", {"queue": "ranked_solo"}),
    ("inicia búsqueda ranked", "league_search", {"queue": "ranked_solo"}),
    ("entra en cola ARAM", "league_search", {"queue": "aram"}),
    ("busca una partida en el LoL", "league_search", {"queue": "normal_draft"}),
    ("quiero buscar una partida en el LoL", "league_search", {"queue": "normal_draft"}),
    ("estado de League", "league_status", {}),
    ("estado de búsqueda de League", "league_search_status", {}),
    ("cancela la búsqueda", "league_cancel", {}),
    ("control multimedia next", "media_action", {"action": "next"}),
    ("crea un temporizador 60", "timer_create", {"seconds": 60, "label": "Pipα timer"}),
    ("lista los temporizadores", "timer_list", {}),
    ("cancela el temporizador abc_123", "timer_cancel", {"timer_id": "abc_123"}),
    ("abre una URL validada https://example.com", "open_url", {"url": "https://example.com"}),
)
_SAFE_COMMANDS = frozenset(
    {
        "system_status",
        "integration_status",
        "system_power",
        "system_network",
        "audio_mute",
        "audio_unmute",
        "audio_volume",
        "media_action",
        "league_status",
        "league_search_status",
        "timer_create",
        "timer_list",
        "timer_cancel",
    }
)
_PLACEHOLDER_PATTERN = re.compile(r"<([^<>]+)>")


def _check(name: str, callback: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    try:
        details = callback() or {}
    except (AppsConfigError, ContactsConfigError, LeagueClientError, ValueError, OSError):
        return {"ok": False, "code": f"{name}_invalid"}
    return {"ok": True, **details}


def _check_apps() -> dict[str, Any]:
    apps = load_apps()
    return {"configured_count": len(apps)}


def _check_contacts() -> dict[str, Any]:
    contacts = load_contacts()
    return {"configured_count": len(contacts), "external_actions_executed": False}


def _check_url_builders() -> dict[str, Any]:
    # These builders are deliberately exercised with fixed synthetic values.
    # None of them opens a browser or includes a local contact/account.
    builders = (
        build_web_search_url("Pipa self test"),
        build_apple_music_search_url("Pipa self test"),
        build_apple_music_browse_url(),
        build_whatsapp_web_url(),
        build_whatsapp_chat_url(_SAMPLE_PHONE),
        build_whatsapp_compose_url(_SAMPLE_PHONE, "Pipa self test"),
        build_discord_app_url(),
        build_discord_channel_url(_SAMPLE_DISCORD_CHANNEL, _SAMPLE_DISCORD_GUILD),
    )
    if not all(isinstance(url, str) and url.startswith(("http://", "https://")) for url in builders):
        raise ValueError("an external URL builder returned an invalid result")
    return {"external_actions_executed": False}


def _check_league_queues() -> dict[str, Any]:
    for queue_name in QUEUE_IDS:
        if resolve_queue_id(queue_name) != QUEUE_IDS[queue_name]:
            raise ValueError("league queue mapping is inconsistent")
    return {"queue_count": len(QUEUE_IDS)}


def _check_league_client() -> dict[str, Any]:
    try:
        find_client_connection()
    except LeagueClientError:
        return {"ready": False, "optional": True}
    return {"ready": True, "optional": True}


def _check_integration_policy() -> dict[str, Any]:
    """Assert that outward integrations keep their human-action boundaries."""

    capabilities = get_capabilities(
        serial_gateway_configured=False,
        serial_gateway_running=False,
        serial_gateway_connected=False,
    )
    integrations = capabilities.get("integrations")
    if not isinstance(integrations, dict):
        raise ValueError("integration capabilities are not an object")

    required_false = (
        ("apple_music", "playback"),
        ("whatsapp", "send_message"),
        ("discord", "start_call"),
        ("codex", "writes_to_chat"),
    )
    required_true = (
        ("apple_music", "media_control"),
        ("apple_music", "requires_manual_selection"),
        ("whatsapp", "requires_manual_send"),
        ("discord", "requires_manual_call"),
    )
    for integration, field in required_false:
        values = integrations.get(integration)
        if not isinstance(values, dict) or values.get(field) is not False:
            raise ValueError(f"{integration}.{field} must remain disabled")
    for integration, field in required_true:
        values = integrations.get(integration)
        if not isinstance(values, dict) or values.get(field) is not True:
            raise ValueError(f"{integration}.{field} must require a human")

    catalog = build_agent_catalog(TimerManager())
    unsafe_tools = {name for name in catalog.names() if catalog.get(name).safety == "unsafe"}
    mapped_tools = set(CONFIRMATION_TOOL_PATHS)
    if mapped_tools != unsafe_tools:
        raise ValueError("unsafe tools and confirmation routes are inconsistent")
    if set(CONFIRMATION_TOOL_PATHS.values()) != LOCAL_CONFIRMATION_PATHS:
        raise ValueError("confirmation route set is inconsistent")
    return {"manual_boundaries": True, "confirmation_mapped_tools": len(mapped_tools)}


def _check_command_routes() -> dict[str, Any]:
    """Exercise the supported voice grammar without invoking any tool."""

    for phrase, expected_tool, expected_arguments in _COMMAND_ROUTE_CASES:
        parsed = parse_text_intent(phrase)
        if parsed is None or parsed.tool_name != expected_tool or parsed.arguments != expected_arguments:
            raise ValueError(f"command route is inconsistent for {expected_tool}")

    catalog = build_agent_catalog(TimerManager())
    public_commands = get_command_catalog()
    public_ids: set[str] = set()
    public_tool_names: set[str] = set()
    structured_commands = 0
    direct_structured_commands = 0
    for command in public_commands:
        if not isinstance(command, dict):
            raise ValueError("public command catalog contains a non-object")
        command_id = command.get("id")
        tool_name = command.get("tool_name")
        if not isinstance(command_id, str) or not command_id.strip() or command_id in public_ids:
            raise ValueError("public command catalog contains invalid or duplicate IDs")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("public command catalog contains an invalid tool name")
        phrase = command.get("phrase")
        if not isinstance(phrase, str) or not phrase.strip():
            raise ValueError("public command catalog contains an invalid phrase")
        placeholders = _PLACEHOLDER_PATTERN.findall(phrase)
        parameters = command.get("parameters")
        if placeholders:
            if not isinstance(parameters, list) or len(parameters) != len(placeholders):
                raise ValueError("structured catalog parameters do not match phrase placeholders")
            structured_commands += 1
        elif parameters is not None:
            if not isinstance(parameters, list) or parameters:
                raise ValueError("catalog exposes invalid parameters without phrase placeholders")
            direct_structured_commands += 1
        public_ids.add(command_id)
        public_tool_names.add(tool_name)
        try:
            definition = catalog.get(tool_name)
        except KeyError as error:
            raise ValueError("public command catalog references an unknown tool") from error
        expected_confirmation = definition.safety == "unsafe"
        if (
            command.get("safety") != definition.safety
            or command.get("requires_confirmation") != expected_confirmation
        ):
            raise ValueError("public command catalog safety is inconsistent")
    unpublished = set(catalog.names()) - public_tool_names
    if unpublished:
        raise ValueError("agent tool is missing from the public command catalog")
    for _phrase, tool_name, _arguments in _COMMAND_ROUTE_CASES:
        expected_safety = "safe" if tool_name in _SAFE_COMMANDS else "unsafe"
        if catalog.get(tool_name).safety != expected_safety:
            raise ValueError(f"command safety is inconsistent: {tool_name}")
    recognized_tool_names = {tool_name for _phrase, tool_name, _arguments in _COMMAND_ROUTE_CASES}
    missing_routes = public_tool_names - recognized_tool_names
    if missing_routes:
        raise ValueError("public command catalog has no parser route")
    confirmation_count = sum(
        catalog.get(tool_name).safety == "unsafe" for _phrase, tool_name, _arguments in _COMMAND_ROUTE_CASES
    )
    return {
        "recognized_commands": len(_COMMAND_ROUTE_CASES),
        "confirmation_gated_commands": confirmation_count,
        "catalog_commands": len(public_commands),
        "structured_commands": structured_commands,
        "direct_structured_commands": direct_structured_commands,
        "unpublished_tools": 0,
        "external_actions_executed": False,
    }


def get_self_test(
    *,
    serial_gateway_configured: bool,
    serial_gateway_running: bool,
    serial_gateway_connected: bool = False,
    mobile_gateway_configured: bool = False,
    mobile_gateway_running: bool = False,
    mobile_gateway_connected: bool = False,
) -> dict[str, Any]:
    """Return bounded, non-sensitive checks suitable for local diagnostics."""

    gateway_ok = not serial_gateway_configured or (serial_gateway_running and serial_gateway_connected)
    mobile_gateway_ok = not mobile_gateway_configured or mobile_gateway_running
    checks: dict[str, dict[str, Any]] = {
        "apps_config": _check("apps_config", _check_apps),
        "contacts_config": _check("contacts_config", _check_contacts),
        "url_builders": _check("url_builders", _check_url_builders),
        "league_queues": _check("league_queues", _check_league_queues),
        "league_client": _check("league_client", _check_league_client),
        "integration_policy": _check("integration_policy", _check_integration_policy),
        "command_routes": _check("command_routes", _check_command_routes),
        "secure_session": _check("secure_session", run_secure_self_test),
        "device_protocol": _check("device_protocol", run_device_protocol_self_test),
        "mobile_protocol": _check("mobile_protocol", run_mobile_protocol_self_test),
        "secure_serial_loopback": _check("secure_serial_loopback", run_secure_serial_self_test),
        "serial_gateway": {
            "ok": gateway_ok,
            "configured": serial_gateway_configured,
            "running": serial_gateway_running,
            "connected": serial_gateway_connected,
            "optional": True,
        },
        "mobile_gateway": {
            "ok": mobile_gateway_ok,
            "configured": mobile_gateway_configured,
            "running": mobile_gateway_running,
            "connected": mobile_gateway_connected,
            "security": "secure-session-v2",
            "optional": True,
        },
    }
    return {
        "success": all(check["ok"] for check in checks.values()),
        "hardware_required": False,
        "checks": checks,
    }
