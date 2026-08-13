"""Small local CLI for exercising the Windows Agent without Pipα hardware.

The CLI intentionally talks only to the loopback agent and exposes the same
bounded integration actions as the REST API. It does not persist credentials,
accept a remote host, or bypass the agent's local-request header.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.capabilities import get_capabilities  # noqa: E402
from tools.diagnostics import get_self_test  # noqa: E402
from tools.mobile_config import inspect_mobile_transport  # noqa: E402
from tools.secure_diagnostics import (  # noqa: E402
    run_mobile_protocol_self_test,
    run_mobile_tcp_self_test,
    run_secure_audio_self_test,
    run_secure_self_test,
)
from tools.security_policy import CLI_CONFIRMATION_COMMANDS, LOCAL_CONFIRMATION_PATHS  # noqa: E402
from tools.timers import validate_timer_id  # noqa: E402

from backend.pipa_core.intents import parse_text_intent  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
LOCAL_HOSTS = frozenset({"127.0.0.1", "::1"})


def _configure_output_encoding() -> None:
    """Keep Spanish/Greek status text printable in legacy Windows consoles."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Embedded callers and test harnesses may expose a fixed stream.
            # JSON remains bounded and the command can still complete.
            continue


def _local_base_url(value: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(value.rstrip("/"))
    try:
        port = parsed.port
    except ValueError as error:
        raise argparse.ArgumentTypeError("El puerto local no es válido.") from error
    if (
        parsed.scheme.lower() != "http"
        or parsed.hostname not in LOCAL_HOSTS
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise argparse.ArgumentTypeError("La URL debe ser HTTP y apuntar a un literal de loopback.")
    return value.rstrip("/")


def _parser() -> argparse.ArgumentParser:
    # Keep argparse help compatible with the legacy Windows console code page.
    parser = argparse.ArgumentParser(description="Cliente local de pruebas de Pipa.")
    parser.add_argument("--base-url", type=_local_base_url, default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    def add_confirmation_flag(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--confirm",
            action="store_true",
            help="Autoriza explícitamente la acción local (sin hardware).",
        )

    commands.add_parser("status", help="Comprueba si el agente responde.")
    commands.add_parser("doctor", help="Comprueba salud, capacidades y protocolo sin efectos secundarios.")
    commands.add_parser("self-test", help="Valida integraciones y configuración sin abrir aplicaciones.")
    commands.add_parser(
        "local-self-test",
        help="Valida el código actual sin depender del agente residente.",
    )
    commands.add_parser("secure-test", help="Valida el cifrado v2 en memoria, sin hardware ni red.")
    commands.add_parser(
        "secure-audio-test",
        help="Valida el contrato de audio cifrado con PCM sintético, sin hardware.",
    )
    commands.add_parser("mobile-test", help="Valida el flujo móvil v2 en memoria, sin hardware ni red.")
    commands.add_parser("mobile-tcp-test", help="Valida el transporte móvil TCP v2 solo en loopback.")
    commands.add_parser(
        "mobile-config", help="Valida la configuración móvil sin abrir puertos ni modificar nada."
    )
    commands.add_parser("capabilities", help="Muestra integraciones y límites actuales.")
    commands.add_parser(
        "local-capabilities",
        help="Muestra la matriz del código actual sin depender del agente residente.",
    )
    commands.add_parser("integration-status", help="Muestra solo el estado de las integraciones.")
    commands.add_parser("commands", help="Muestra frases y acciones disponibles, sin ejecutar nada.")
    commands.add_parser("protocol", help="Muestra herramientas y estado del gateway.")
    commands.add_parser("system-status", help="Consulta el estado resumido del PC.")
    intent = commands.add_parser("intent", help="Comprueba cómo interpreta una frase sin ejecutar nada.")
    intent.add_argument("text", nargs="+", help="Frase que enviaría el dispositivo.")
    preview = commands.add_parser(
        "preview",
        help="Muestra la herramienta, argumentos y confirmación que usaría una frase.",
    )
    preview.add_argument("text", nargs="+", help="Frase que enviaría el dispositivo.")
    open_app = commands.add_parser("open-app", help="Abre una aplicación de apps.json.")
    open_app.add_argument("app")
    add_confirmation_flag(open_app)
    codex_open = commands.add_parser("codex-open", help="Abre Codex sin escribir en ningún chat.")
    add_confirmation_flag(codex_open)
    web_search = commands.add_parser("web-search", help="Abre una búsqueda web.")
    web_search.add_argument("query", nargs="+", help="Texto que se buscará.")
    add_confirmation_flag(web_search)
    open_url = commands.add_parser("open-url", help="Abre una URL HTTP(S) validada.")
    open_url.add_argument("url")
    add_confirmation_flag(open_url)
    music_open = commands.add_parser("music-open", help="Abre Apple Music o su catálogo web.")
    add_confirmation_flag(music_open)
    music_search = commands.add_parser("music-search", help="Abre una búsqueda de Apple Music.")
    music_search.add_argument("term", nargs="+", help="Artista, canción o álbum.")
    add_confirmation_flag(music_search)
    whatsapp_open = commands.add_parser("whatsapp-open", help="Abre WhatsApp Web sin enviar nada.")
    add_confirmation_flag(whatsapp_open)
    whatsapp = commands.add_parser("whatsapp-compose", help="Prepara un mensaje sin pulsar Enviar.")
    whatsapp.add_argument("phone", help="Teléfono internacional.")
    whatsapp.add_argument("message", nargs="+", help="Texto del mensaje.")
    add_confirmation_flag(whatsapp)
    whatsapp_contact = commands.add_parser(
        "whatsapp-contact", help="Prepara WhatsApp usando un alias local; no pulsa Enviar."
    )
    whatsapp_contact.add_argument("contact")
    whatsapp_contact.add_argument("message", nargs="+", help="Texto del mensaje.")
    add_confirmation_flag(whatsapp_contact)
    whatsapp_contact_open = commands.add_parser(
        "whatsapp-contact-open", help="Abre el chat de un alias local sin preparar ni enviar mensajes."
    )
    whatsapp_contact_open.add_argument("contact")
    add_confirmation_flag(whatsapp_contact_open)
    whatsapp_phone_open = commands.add_parser(
        "whatsapp-phone-open", help="Abre un chat de WhatsApp por teléfono sin enviar nada."
    )
    whatsapp_phone_open.add_argument("phone")
    add_confirmation_flag(whatsapp_phone_open)
    discord_open = commands.add_parser("discord-open", help="Abre Discord sin iniciar llamadas.")
    add_confirmation_flag(discord_open)
    discord = commands.add_parser("discord-channel", help="Abre un canal o DM de Discord.")
    discord.add_argument("channel_id")
    discord.add_argument("--guild-id")
    add_confirmation_flag(discord)
    discord_call_channel = commands.add_parser(
        "discord-call-channel", help="Abre el destino de llamada; no pulsa Llamar."
    )
    discord_call_channel.add_argument("channel_id")
    discord_call_channel.add_argument("--guild-id")
    add_confirmation_flag(discord_call_channel)
    discord_contact = commands.add_parser(
        "discord-contact", help="Abre Discord usando un alias local; no inicia llamadas."
    )
    discord_contact.add_argument("contact")
    add_confirmation_flag(discord_contact)
    discord_call = commands.add_parser(
        "discord-call", help="Abre el destino de Discord; no pulsa el botón de llamada."
    )
    discord_call.add_argument("contact")
    add_confirmation_flag(discord_call)
    league_open = commands.add_parser("league-open", help="Abre el cliente de League.")
    add_confirmation_flag(league_open)
    commands.add_parser("league-status", help="Consulta lobby y matchmaking.")
    commands.add_parser("league-search-status", help="Consulta solo el estado de búsqueda.")
    league_search = commands.add_parser("league-search", help="Inicia matchmaking en una cola allowlisted.")
    league_search.add_argument("queue", nargs="?", default="normal_draft")
    add_confirmation_flag(league_search)
    league_cancel = commands.add_parser("league-cancel", help="Cancela la búsqueda activa.")
    add_confirmation_flag(league_cancel)
    audio_volume = commands.add_parser("audio-volume", help="Consulta o ajusta el volumen.")
    audio_volume.add_argument("percent", nargs="?", type=int)
    commands.add_parser("audio-mute", help="Silencia el audio.")
    commands.add_parser("audio-unmute", help="Activa el audio.")
    commands.add_parser("power-status", help="Consulta batería y alimentación.")
    commands.add_parser("network-status", help="Consulta el estado de las interfaces de red.")
    media_action = commands.add_parser("media-action", help="Envía una acción multimedia allowlisted.")
    media_action.add_argument("action")
    commands.add_parser("timer-list", help="Lista temporizadores activos.")
    timer_create = commands.add_parser("timer-create", help="Crea un temporizador local.")
    timer_create.add_argument("seconds", type=int)
    timer_create.add_argument("label", nargs="+", default=["Pipα timer"])
    timer_cancel = commands.add_parser("timer-cancel", help="Cancela un temporizador.")
    timer_cancel.add_argument("timer_id")
    lock = commands.add_parser("lock", help="Bloquea el PC.")
    add_confirmation_flag(lock)
    return parser


def _request(base_url: str, method: str, path: str, payload: dict[str, object] | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if method in {"POST", "DELETE"}:
        headers["X-Pipa-Local-Request"] = "1"
    if path in LOCAL_CONFIRMATION_PATHS and method in {"POST", "DELETE"}:
        headers["X-Pipa-Local-Confirmation"] = "1"
    request = Request(base_url + path, method=method, headers=headers, data=body)
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read(64 * 1024)
    except HTTPError as error:
        # Do not reflect the agent's response body. It can contain request
        # details or implementation data that should stay on the host.
        error.close()
        raise RuntimeError(f"El agente rechazó la solicitud (HTTP {error.code}).") from error
    except URLError as error:
        raise RuntimeError("No se pudo conectar con el agente local.") from error
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("El agente devolvió JSON inválido.") from error
    if not isinstance(result, dict):
        raise RuntimeError("El agente devolvió una respuesta inesperada.")
    return result


def _route(arguments: argparse.Namespace) -> tuple[str, str, dict[str, object] | None]:
    command = arguments.command
    if command == "status":
        return "GET", "/status", None
    if command == "capabilities":
        return "GET", "/capabilities", None
    if command == "integration-status":
        return "GET", "/integrations/status", None
    if command == "commands":
        return "GET", "/commands", None
    if command == "self-test":
        return "GET", "/self-test", None
    if command == "protocol":
        return "GET", "/pipa/protocol", None
    if command == "system-status":
        return "GET", "/system/status", None
    if command == "open-app":
        return "POST", "/open-app", {"app": arguments.app}
    if command == "codex-open":
        return "POST", "/codex/open", {}
    if command == "web-search":
        return "POST", "/web/search", {"query": " ".join(arguments.query)}
    if command == "open-url":
        return "POST", "/open-url", {"url": arguments.url}
    if command == "music-open":
        return "POST", "/music/open", {}
    if command == "music-search":
        return "POST", "/music/search", {"term": " ".join(arguments.term)}
    if command == "whatsapp-open":
        return "POST", "/whatsapp/open", {}
    if command == "whatsapp-compose":
        return "POST", "/whatsapp/compose", {"phone": arguments.phone, "message": " ".join(arguments.message)}
    if command == "whatsapp-contact":
        return (
            "POST",
            "/whatsapp/contact/compose",
            {
                "contact": arguments.contact,
                "message": " ".join(arguments.message),
            },
        )
    if command == "whatsapp-contact-open":
        return "POST", "/whatsapp/contact/open", {"contact": arguments.contact}
    if command == "whatsapp-phone-open":
        return "POST", "/whatsapp/phone/open", {"phone": arguments.phone}
    if command == "discord-open":
        return "POST", "/discord/open", {}
    if command == "discord-channel":
        payload: dict[str, object] = {"channel_id": arguments.channel_id}
        if arguments.guild_id is not None:
            payload["guild_id"] = arguments.guild_id
        return "POST", "/discord/channel/open", payload
    if command == "discord-call-channel":
        payload = {"channel_id": arguments.channel_id}
        if arguments.guild_id is not None:
            payload["guild_id"] = arguments.guild_id
        return "POST", "/discord/channel/call", payload
    if command == "discord-contact":
        return "POST", "/discord/contact/open", {"contact": arguments.contact}
    if command == "discord-call":
        return "POST", "/discord/contact/call", {"contact": arguments.contact}
    if command == "league-open":
        return "POST", "/league/open", {}
    if command == "league-status":
        return "GET", "/league/status", None
    if command == "league-search-status":
        return "GET", "/league/search/status", None
    if command == "league-search":
        return "POST", "/league/search", {"queue": arguments.queue}
    if command == "league-cancel":
        return "DELETE", "/league/search", None
    if command == "audio-volume":
        if arguments.percent is None:
            return "GET", "/audio/volume", None
        return "POST", "/audio/volume", {"percent": arguments.percent}
    if command == "audio-mute":
        return "POST", "/audio/mute", {}
    if command == "audio-unmute":
        return "POST", "/audio/unmute", {}
    if command == "power-status":
        return "GET", "/system/power", None
    if command == "network-status":
        return "GET", "/system/network", None
    if command == "media-action":
        return "POST", "/media/action", {"action": arguments.action}
    if command == "timer-list":
        return "GET", "/timers", None
    if command == "timer-create":
        return "POST", "/timers", {"seconds": arguments.seconds, "label": " ".join(arguments.label)}
    if command == "timer-cancel":
        try:
            timer_id = validate_timer_id(arguments.timer_id)
        except ValueError as error:
            raise RuntimeError("El identificador del temporizador no es válido.") from error
        return "DELETE", f"/timers/{quote(timer_id, safe='')}", None
    if command == "lock":
        return "POST", "/system/lock", {}
    raise RuntimeError(f"Comando no soportado: {command}")


def _inspect_intent(text: str) -> dict[str, object]:
    """Show deterministic parsing without contacting the agent or opening apps."""

    parsed = parse_text_intent(text)
    if parsed is None:
        return {"recognized": False, "message": "La frase no tiene un comando compatible."}
    return {
        "recognized": True,
        "tool_name": parsed.tool_name,
        "arguments": parsed.arguments,
        "side_effects": False,
    }


def _secure_test() -> dict[str, object]:
    """Run the secure protocol check without requiring the local agent."""

    return {
        "success": True,
        "hardware_required": False,
        "checks": {"secure_session": {"ok": True, **run_secure_self_test()}},
    }


def _local_self_test() -> dict[str, object]:
    """Run diagnostics from this checkout, without contacting the agent.

    ``self-test`` intentionally asks the resident process so it reflects the
    process currently serving requests. This variant is useful immediately
    after an update, before restarting the agent, and makes the distinction
    explicit instead of silently reporting stale in-memory code.
    """

    return get_self_test(
        serial_gateway_configured=False,
        serial_gateway_running=False,
        serial_gateway_connected=False,
        mobile_gateway_configured=False,
        mobile_gateway_running=False,
        mobile_gateway_connected=False,
    )


def _local_capabilities() -> dict[str, object]:
    """Read the current checkout's capability matrix without HTTP or side effects."""

    return get_capabilities(
        serial_gateway_configured=False,
        serial_gateway_running=False,
        serial_gateway_connected=False,
        mobile_gateway_configured=False,
        mobile_gateway_running=False,
        mobile_gateway_connected=False,
    )


def _doctor(base_url: str) -> dict[str, object]:
    """Run read-only local health checks and return only bounded JSON data."""

    def healthy(name: str, result: dict) -> bool:
        if result.get("success") is not True:
            return False
        if name == "agent":
            return result.get("pc") == "online"
        if name == "capabilities":
            return isinstance(result.get("integrations"), dict)
        if name == "commands":
            return isinstance(result.get("commands"), list)
        if name == "protocol":
            return result.get("protocol_version") == 1 and isinstance(result.get("tool_names"), list)
        if name == "self_test":
            return isinstance(result.get("checks"), dict)
        return False

    checks: dict[str, object] = {}
    requests = (
        ("agent", "GET", "/status"),
        ("capabilities", "GET", "/capabilities"),
        ("commands", "GET", "/commands"),
        ("protocol", "GET", "/pipa/protocol"),
        ("self_test", "GET", "/self-test"),
    )
    for name, method, path in requests:
        try:
            result = _request(base_url, method, path)
            checks[name] = {
                "ok": healthy(name, result),
                "success": result.get("success"),
            }
        except RuntimeError:
            checks[name] = {"ok": False, "success": False}
    return {"success": all(item["ok"] for item in checks.values()), "checks": checks}


def _preview_intent(text: str) -> dict[str, object]:
    """Describe routing and safety without executing the selected tool."""

    parsed = parse_text_intent(text)
    if parsed is None:
        return {"recognized": False, "message": "La frase no tiene un comando compatible."}

    from tools.agent_catalog import build_agent_catalog
    from tools.integration_catalog import get_command_catalog
    from tools.timers import TimerManager

    definition = build_agent_catalog(TimerManager()).get(parsed.tool_name)
    try:
        definition.validate_arguments(parsed.arguments)
    except (KeyError, TypeError, ValueError):
        arguments_valid = False
    else:
        arguments_valid = True

    catalog_entry = next(
        (command for command in get_command_catalog() if command.get("tool_name") == parsed.tool_name),
        None,
    )
    description = (
        catalog_entry.get("description")
        if isinstance(catalog_entry, dict) and isinstance(catalog_entry.get("description"), str)
        else "Herramienta local de Pipa."
    )
    return {
        "recognized": True,
        "tool_name": parsed.tool_name,
        "arguments": parsed.arguments,
        "arguments_valid": arguments_valid,
        "safety": definition.safety,
        "requires_confirmation": definition.safety == "unsafe",
        "side_effects": False,
        "message": (
            definition.confirm_summary(parsed.arguments)
            if arguments_valid and definition.safety == "unsafe" and definition.confirm_summary is not None
            else (
                "La frase se reconoce, pero sus argumentos o la configuración local todavía no están listos."
                if not arguments_valid
                else "La herramienta se ejecutaría sin confirmación adicional."
            )
        ),
        "description": description,
    }


def main(argv: Sequence[str] | None = None) -> int:
    _configure_output_encoding()
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "doctor":
            print(json.dumps(_doctor(arguments.base_url), ensure_ascii=False, indent=2))
            return 0
        if arguments.command == "intent":
            print(json.dumps(_inspect_intent(" ".join(arguments.text)), ensure_ascii=False, indent=2))
            return 0
        if arguments.command == "preview":
            print(json.dumps(_preview_intent(" ".join(arguments.text)), ensure_ascii=False, indent=2))
            return 0
        if arguments.command == "secure-test":
            print(json.dumps(_secure_test(), ensure_ascii=False, indent=2))
            return 0
        if arguments.command == "secure-audio-test":
            result = {
                "success": True,
                "hardware_required": False,
                "checks": {"secure_audio": run_secure_audio_self_test()},
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if arguments.command == "local-self-test":
            result = _local_self_test()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["success"] else 1
        if arguments.command == "local-capabilities":
            result = _local_capabilities()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["success"] else 1
        if arguments.command == "mobile-test":
            print(
                json.dumps(
                    {
                        "success": True,
                        "hardware_required": False,
                        "checks": {"mobile_protocol": run_mobile_protocol_self_test()},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if arguments.command == "mobile-tcp-test":
            print(
                json.dumps(
                    {
                        "success": True,
                        "hardware_required": False,
                        "checks": {"mobile_tcp": run_mobile_tcp_self_test()},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if arguments.command == "mobile-config":
            result = inspect_mobile_transport()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["success"] else 1
        if arguments.command in CLI_CONFIRMATION_COMMANDS and not arguments.confirm:
            raise RuntimeError(
                "Esta acción requiere autorización explícita; añade --confirm. "
                "Usa preview para inspeccionarla sin ejecutar nada."
            )
        method, path, payload = _route(arguments)
        result = _request(arguments.base_url, method, path, payload)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
