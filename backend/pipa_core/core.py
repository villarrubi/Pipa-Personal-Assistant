"""Orchestration core for authenticated device sessions."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from trusted_unlock_protocol import (
    AuthorizationVerifier,
    SignedChallenge,
)

from .confirmations import ConfirmationError
from .intents import parse_text_intent
from .memory import MemoryStore
from .protocol import ClientMessage, server_message
from .state import SessionRegistry
from .tools import ToolRouter

CONFIRMATION_CAPABILITIES = frozenset({"display", "touch"})
MAX_CATALOG_COMMANDS = 64
MAX_CATALOG_FIELD_LENGTH = 256
MAX_CATALOG_PARAMETERS = 8
MAX_CATALOG_PARAMETER_OPTIONS = 16
MAX_CATALOG_PARAMETER_TEXT_LENGTH = 128
_CATALOG_FIELDS = frozenset(
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
_CATALOG_PARAMETER_FIELDS = frozenset({"name", "label", "kind", "max_length", "options"})
_CATALOG_PARAMETER_KINDS = frozenset(
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
_CATALOG_PARAMETER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
MAX_CAPABILITY_GROUPS = 16
MAX_CAPABILITY_FIELDS = 16
MAX_CAPABILITY_KEY_LENGTH = 64
MAX_CAPABILITY_TEXT_LENGTH = 128
_CAPABILITY_GROUPS = frozenset({"web_search", "apple_music", "whatsapp", "discord", "league", "codex"})
_DEVICE_CONFIRMATION_SUMMARIES = {
    "open_app": "Abrir una aplicación configurada.",
    "open_codex": "Abrir Codex.",
    "web_search": "Buscar en Internet.",
    "music_search": "Buscar en Apple Music.",
    "music_open": "Abrir Apple Music.",
    "league_open": "Abrir League of Legends.",
    "discord_open_app": "Abrir Discord.",
    "discord_open": "Abrir un canal de Discord.",
    "discord_call_channel": "Preparar una llamada de Discord; el inicio será manual.",
    "discord_contact": "Abrir un contacto de Discord.",
    "discord_call": "Preparar una llamada de Discord; el inicio será manual.",
    "whatsapp_compose": "Preparar un mensaje de WhatsApp; el envío será manual.",
    "whatsapp_contact": "Preparar un mensaje de WhatsApp; el envío será manual.",
    "whatsapp_contact_open": "Abrir un chat de WhatsApp.",
    "whatsapp_phone_open": "Abrir un chat de WhatsApp.",
    "whatsapp_open": "Abrir WhatsApp Web.",
    "league_search": "Buscar una partida en League.",
    "league_cancel": "Cancelar la búsqueda de League.",
    "system_lock": "Bloquear el ordenador.",
    "open_url": "Abrir una URL validada.",
}
_CAPABILITY_BOOLEAN_FIELDS = frozenset(
    {
        "available",
        "app_configured",
        "search",
        "playback",
        "media_control",
        "requires_manual_selection",
        "open_web",
        "open_contact",
        "contact_aliases_configured",
        "prepare_message",
        "send_message",
        "requires_manual_send",
        "open_app",
        "open_channel",
        "start_call",
        "requires_manual_call",
        "client_ready",
        "open_client",
        "matchmaking",
        "cancel_matchmaking",
        "accept_match",
        "requires_manual_accept",
        "writes_to_chat",
        "requires_confirmation",
    }
)
_CAPABILITY_STRING_FIELDS = frozenset({"execution"})
_CAPABILITY_LIST_FIELDS = frozenset({"queues"})
_PRE_HELLO_MESSAGE_TYPES = frozenset({"ping", "device_status", "device_hello", "abort"})


def _is_safe_catalog_text(value: str) -> bool:
    return not any(
        ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        or 0x200B <= ord(character) <= 0x200F
        or 0x202A <= ord(character) <= 0x202E
        or 0x2060 <= ord(character) <= 0x2069
        or ord(character) == 0xFEFF
        for character in value
    )


def _validate_catalog_parameters(value: Any) -> list[dict[str, Any]]:
    """Validate structured input metadata without accepting user data."""

    if not isinstance(value, list) or len(value) > MAX_CATALOG_PARAMETERS:
        raise ValueError("invalid catalog parameters")

    validated: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for parameter in value:
        if not isinstance(parameter, dict) or set(parameter) - _CATALOG_PARAMETER_FIELDS:
            raise ValueError("invalid catalog parameter fields")
        name = parameter.get("name")
        label = parameter.get("label")
        kind = parameter.get("kind")
        max_length = parameter.get("max_length")
        if (
            not isinstance(name, str)
            or _CATALOG_PARAMETER_NAME.fullmatch(name) is None
            or name in seen_names
            or not isinstance(label, str)
            or not label.strip()
            or len(label) > MAX_CATALOG_PARAMETER_TEXT_LENGTH
            or not _is_safe_catalog_text(label)
            or not isinstance(kind, str)
            or kind not in _CATALOG_PARAMETER_KINDS
            or isinstance(max_length, bool)
            or not isinstance(max_length, int)
            or not 1 <= max_length <= 4096
        ):
            raise ValueError("invalid catalog parameter")

        options = parameter.get("options", [])
        if (
            not isinstance(options, list)
            or len(options) > MAX_CATALOG_PARAMETER_OPTIONS
            or not all(
                isinstance(option, str)
                and option.strip()
                and len(option) <= MAX_CATALOG_PARAMETER_TEXT_LENGTH
                and _is_safe_catalog_text(option)
                for option in options
            )
        ):
            raise ValueError("invalid catalog parameter options")
        if len(set(options)) != len(options):
            raise ValueError("invalid catalog parameter options")

        seen_names.add(name)
        normalized: dict[str, Any] = {
            "name": name,
            "label": label.strip(),
            "kind": kind,
            "max_length": max_length,
        }
        if options:
            normalized["options"] = [option.strip() for option in options]
        validated.append(normalized)
    return validated


def _validate_catalog_default_arguments(value: Any) -> dict[str, str]:
    """Validate fixed typed arguments for direct structured commands."""

    if not isinstance(value, dict) or not value or len(value) > MAX_CATALOG_PARAMETERS:
        raise ValueError("invalid catalog default arguments")

    validated: dict[str, str] = {}
    for name, argument in value.items():
        if (
            not isinstance(name, str)
            or _CATALOG_PARAMETER_NAME.fullmatch(name) is None
            or not isinstance(argument, str)
            or not argument.strip()
            or len(argument) > MAX_CATALOG_PARAMETER_TEXT_LENGTH
            or not _is_safe_catalog_text(argument)
        ):
            raise ValueError("invalid catalog default argument")
        validated[name] = argument.strip()
    return validated


def _validate_capability_catalog(value: Any) -> dict[str, dict[str, Any]]:
    """Validate the small, non-sensitive capability matrix sent to a UI.

    Capability values are deliberately limited to booleans, short strings and
    short string lists.  Rejecting nested objects, numbers and arbitrary JSON
    here prevents a future adapter from accidentally returning paths, IDs,
    URLs, tokens or raw integration responses through the catalog envelope.
    """

    if not isinstance(value, dict) or len(value) > MAX_CAPABILITY_GROUPS:
        raise ValueError("invalid capability groups")

    validated: dict[str, dict[str, Any]] = {}
    for group_name, fields in value.items():
        if (
            not isinstance(group_name, str)
            or not group_name.strip()
            or len(group_name) > MAX_CAPABILITY_KEY_LENGTH
            or group_name.strip() not in _CAPABILITY_GROUPS
            or not isinstance(fields, dict)
            or len(fields) > MAX_CAPABILITY_FIELDS
        ):
            raise ValueError("invalid capability group")

        safe_fields: dict[str, Any] = {}
        for field_name, field_value in fields.items():
            if (
                not isinstance(field_name, str)
                or not field_name.strip()
                or len(field_name) > MAX_CAPABILITY_KEY_LENGTH
                or field_name.strip()
                not in (_CAPABILITY_BOOLEAN_FIELDS | _CAPABILITY_STRING_FIELDS | _CAPABILITY_LIST_FIELDS)
            ):
                raise ValueError("invalid capability field")
            field_name = field_name.strip()
            if field_name in _CAPABILITY_BOOLEAN_FIELDS and isinstance(field_value, bool):
                safe_fields[field_name.strip()] = field_value
            elif field_name in _CAPABILITY_STRING_FIELDS and isinstance(field_value, str):
                if (
                    not field_value.strip()
                    or len(field_value) > MAX_CAPABILITY_TEXT_LENGTH
                    or any(ord(character) < 0x20 or ord(character) == 0x7F for character in field_value)
                ):
                    raise ValueError("invalid capability text")
                safe_fields[field_name.strip()] = field_value.strip()
            elif field_name in _CAPABILITY_LIST_FIELDS and isinstance(field_value, list):
                if len(field_value) > MAX_CAPABILITY_FIELDS or not all(
                    isinstance(item, str)
                    and item.strip()
                    and len(item) <= MAX_CAPABILITY_TEXT_LENGTH
                    and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in item)
                    for item in field_value
                ):
                    raise ValueError("invalid capability list")
                safe_fields[field_name.strip()] = [item.strip() for item in field_value]
            else:
                raise ValueError("invalid capability value")
        validated[group_name.strip()] = safe_fields
    return validated


class PipaCore:
    def __init__(
        self,
        verifier: AuthorizationVerifier,
        router: ToolRouter,
        memory: MemoryStore | None = None,
        command_catalog: Callable[[], list[dict[str, Any]]] | None = None,
        capability_catalog: Callable[[], dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.verifier = verifier
        self.router = router
        self.sessions = SessionRegistry()
        self.memory = memory or MemoryStore()
        self.command_catalog = command_catalog
        self.capability_catalog = capability_catalog

    def create_challenge(self, device_id: str):
        return self.verifier.create_challenge(device_id, operation="session")

    def tool_names(self) -> list[str]:
        return sorted({*self.router.catalog.names(), "remember_fact", "recall_memory"})

    def authenticate(
        self,
        device_id: str,
        challenge_id: str,
        signature: str,
        *,
        firmware_version: str | None = None,
        capabilities: list[str] | None = None,
    ):
        authorization = self.verifier.verify_response(
            SignedChallenge(
                challenge_id=challenge_id,
                device_id=device_id,
                signature=signature,
            )
        )
        return self.sessions.create(
            authorization.device_id,
            firmware_version=firmware_version,
            capabilities=tuple(capabilities or ()),
        )

    def close(self, session_id: str) -> None:
        self.router.cancel_pending(session_id)
        self.sessions.remove(session_id)

    def handle(self, session_id: str, message: ClientMessage) -> list[dict[str, Any]]:
        session = self.sessions.get(session_id)
        if session is None:
            return [server_message("error", code="unknown_session", message="Sesión desconocida.")]

        session.touch()

        if message.type == "ping":
            return [server_message("pong", request_id=message.fields.get("request_id"))]
        if message.type == "device_status":
            session.battery_percent = message.fields["battery_percent"]
            session.wifi_rssi = message.fields["wifi_rssi"]
            return [server_message("status_ack")]
        if message.type == "device_hello":
            if session.capabilities_initialized:
                return [server_message("error", code="device_hello_not_expected")]
            session.firmware_version = message.fields.get("firmware_version")
            session.capabilities = tuple(message.fields["capabilities"])
            session.capabilities_initialized = True
            return [server_message("device_hello_ack")]
        if not session.capabilities_initialized and message.type not in _PRE_HELLO_MESSAGE_TYPES:
            return [
                server_message(
                    "error",
                    code="device_hello_required",
                    message="El dispositivo aún no está listo.",
                )
            ]
        if message.type == "catalog_request":
            return self._catalog_response()

        if session.state == "confirm" and message.type not in {"ping", "device_status", "abort", "confirm"}:
            return [
                server_message(
                    "error",
                    code="confirmation_required",
                    message="Responde a la confirmación pendiente antes de continuar.",
                ),
                session.ui_message(),
            ]

        if message.type in {"wake", "hold_start"}:
            session.set_state("listening")
            return [session.ui_message()]
        if message.type in {"hold_end", "audio_end"}:
            # There is no STT/audio transport in protocol v1 yet. Do not leave
            # the physical UI in "thinking" forever after a recording ends.
            session.set_state("idle", caption="La voz aún no está disponible.")
            return [
                server_message(
                    "error",
                    code="voice_unavailable",
                    message="La voz aún no está disponible.",
                ),
                session.ui_message(),
            ]
        if message.type == "abort":
            self.router.cancel_pending(session.session_id)
            session.set_state("idle")
            return [server_message("tts_aborted"), session.ui_message()]
        if message.type == "gesture":
            return [server_message("gesture_ack", gesture=message.fields["gesture"])]
        if message.type == "text_input":
            intent = parse_text_intent(message.fields["text"])
            if intent is None:
                session.set_state("idle", caption="Todavía no conozco ese comando.")
                return [
                    server_message(
                        "error",
                        code="unsupported_text_intent",
                        message="Comando no reconocido; usa un tool_call o una frase compatible.",
                    ),
                    session.ui_message(),
                ]
            return self._run_tool(session, intent.tool_name, intent.arguments)
        if message.type == "tool_call":
            return self._run_tool(
                session,
                str(message.fields["name"]),
                message.fields["arguments"],
                call_id=message.fields.get("call_id"),
            )
        if message.type == "confirm":
            try:
                result = self.router.resolve_confirmation(
                    str(message.fields["confirmation_id"]),
                    bool(message.fields["accepted"]),
                    owner_id=session.session_id,
                )
            except (ConfirmationError, KeyError, ValueError):
                self.router.cancel_pending(session.session_id)
                session.set_state("idle", caption="La confirmación ha caducado o no es válida.")
                return [
                    server_message(
                        "error",
                        code="confirmation_failed",
                        message="La confirmación ha caducado o no es válida.",
                    ),
                    session.ui_message(),
                ]
            except Exception:
                # A confirmed adapter may still fail because an external app or
                # local client disappeared between preview and execution. The
                # confirmation has already been consumed, so fail closed and
                # keep the transport/session alive without exposing exception
                # text, URLs, tokens or handler data to the device.
                self.router.cancel_pending(session.session_id)
                session.set_state("idle", caption="La herramienta ha fallado.")
                return [
                    server_message("error", code="tool_failed", message="La herramienta ha fallado."),
                    session.ui_message(),
                ]
            caption = (
                "Acción cancelada."
                if result["status"] == "rejected"
                else self._safe_result_caption(str(result["tool_name"]), result["result"])
            )
            session.set_state("idle", caption=caption)
            return [
                self._device_tool_result(
                    str(result["tool_name"]),
                    result,
                    call_id=result.get("call_id"),
                ),
                session.ui_message(),
            ]

        return [server_message("error", code="unsupported_message", message=message.type)]

    def _catalog_response(self) -> list[dict[str, Any]]:
        """Return only bounded, UI-safe command metadata over an authenticated session."""

        if self.command_catalog is None:
            catalog_fields: dict[str, Any] = {"commands": []}
            if self.capability_catalog is not None:
                try:
                    catalog_fields["capabilities"] = _validate_capability_catalog(self.capability_catalog())
                except Exception:
                    return [server_message("error", code="catalog_unavailable")]
            return [server_message("catalog", **catalog_fields)]
        try:
            values = self.command_catalog()
            if not isinstance(values, list) or len(values) > MAX_CATALOG_COMMANDS:
                raise ValueError("catalog has too many commands")
            commands: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for value in values:
                if not isinstance(value, dict) or set(value) - _CATALOG_FIELDS:
                    raise ValueError("catalog entry has invalid fields")
                command_id = value.get("id")
                tool_name = value.get("tool_name")
                phrase = value.get("phrase")
                description = value.get("description")
                safety = value.get("safety")
                requires_confirmation = value.get("requires_confirmation")
                parameters = (
                    _validate_catalog_parameters(value["parameters"]) if "parameters" in value else None
                )
                default_arguments = (
                    _validate_catalog_default_arguments(value["default_arguments"])
                    if "default_arguments" in value
                    else None
                )
                if default_arguments is not None and parameters:
                    raise ValueError("fixed arguments cannot accompany editable parameters")
                text_fields = (command_id, tool_name, phrase, description)
                if any(
                    not isinstance(item, str) or not item.strip() or len(item) > MAX_CATALOG_FIELD_LENGTH
                    for item in text_fields
                ):
                    raise ValueError("catalog entry contains invalid text")
                if safety not in {"safe", "unsafe"} or not isinstance(requires_confirmation, bool):
                    raise ValueError("catalog entry contains invalid safety metadata")
                definition = self.router.catalog.get(tool_name.strip())
                expected_confirmation = definition.safety == "unsafe"
                if safety != definition.safety or requires_confirmation != expected_confirmation:
                    raise ValueError("catalog entry does not match the registered tool")
                command_id = command_id.strip()
                if command_id in seen_ids:
                    raise ValueError("catalog contains duplicate command IDs")
                seen_ids.add(command_id)
                command = {
                    "id": command_id,
                    "tool_name": tool_name.strip(),
                    "phrase": phrase.strip(),
                    "description": description.strip(),
                    "safety": safety,
                    "requires_confirmation": requires_confirmation,
                }
                if parameters is not None:
                    command["parameters"] = parameters
                if default_arguments is not None:
                    command["default_arguments"] = default_arguments
                commands.append(command)
        except Exception:
            return [server_message("error", code="catalog_unavailable")]
        catalog_fields: dict[str, Any] = {"commands": commands}
        if self.capability_catalog is not None:
            try:
                catalog_fields["capabilities"] = _validate_capability_catalog(self.capability_catalog())
            except Exception:
                return [server_message("error", code="catalog_unavailable")]
        return [server_message("catalog", **catalog_fields)]

    def _run_tool(
        self,
        session,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str | None = None,
    ) -> list[dict[str, Any]]:
        session.set_state("thinking")
        if tool_name == "remember_fact":
            try:
                result = self.memory.remember(session.device_id, str(arguments.get("fact", "")))
            except ValueError:
                session.set_state("idle", caption="No se pudo guardar la memoria.")
                return [
                    server_message("error", code="memory_failed", message="No se pudo guardar la memoria."),
                    session.ui_message(),
                ]
            session.set_state("idle")
            return [
                self._device_tool_result("remember_fact", {"status": "completed", "result": result}),
                session.ui_message(),
            ]
        if tool_name == "recall_memory":
            result = self.memory.recall(session.device_id)
            session.set_state("idle")
            return [
                self._device_tool_result("recall_memory", {"status": "completed", "result": result}),
                session.ui_message(),
            ]
        try:
            definition = self.router.catalog.get(tool_name)
        except KeyError:
            definition = None
        if (
            definition is not None
            and definition.safety == "unsafe"
            and not CONFIRMATION_CAPABILITIES.issubset(session.capabilities)
        ):
            session.set_state("idle", caption="Falta la pantalla táctil de confirmación.")
            return [
                server_message(
                    "error",
                    code="confirmation_unavailable",
                    message="La acción requiere pantalla y toque disponibles.",
                ),
                session.ui_message(),
            ]
        try:
            invocation = self.router.invoke(
                tool_name,
                arguments,
                owner_id=session.session_id,
                call_id=call_id,
            )
        except (KeyError, ValueError, ConfirmationError):
            session.set_state("idle", caption="No he podido ejecutar esa acción.")
            return [
                server_message("error", code="tool_failed", message="No he podido ejecutar esa acción."),
                session.ui_message(),
            ]
        except Exception:
            session.set_state("idle", caption="La herramienta ha fallado.")
            return [
                server_message("error", code="tool_failed", message="La herramienta ha fallado."),
                session.ui_message(),
            ]

        if invocation["status"] == "needs_confirmation":
            session.set_state("confirm")
            confirmation = invocation["confirmation"]
            confirmation_fields: dict[str, Any] = {
                "confirmation_id": confirmation["confirmation_id"],
                "tool_name": confirmation["tool_name"],
                "summary": self._device_confirmation_summary(str(confirmation["tool_name"])),
                "expires_at": confirmation["expires_at"],
            }
            if confirmation.get("call_id") is not None:
                confirmation_fields["call_id"] = confirmation["call_id"]
            return [
                server_message("confirm_request", **confirmation_fields),
                session.ui_message(),
            ]

        session.set_state("idle", caption=self._safe_result_caption(tool_name, invocation["result"]))
        return [
            self._device_tool_result(tool_name, invocation, call_id=call_id),
            session.ui_message(),
        ]

    @staticmethod
    def _device_confirmation_summary(tool_name: str) -> str:
        """Return a fixed confirmation label without copying tool arguments.

        The local router keeps the full summary for local callers, but a
        physical/mobile device does not need a phone, message, URL, contact,
        or client ID merely to approve the guarded operation. The external
        application remains visible for the final human review where needed.
        """

        return _DEVICE_CONFIRMATION_SUMMARIES.get(tool_name, "Confirmar acción externa.")

    @staticmethod
    def _device_tool_result(
        tool_name: str,
        invocation: dict[str, Any],
        *,
        call_id: str | None = None,
    ) -> dict[str, Any]:
        """Return a non-sensitive completion envelope for the physical device.

        Tool results stay inside the Windows agent. The device only needs to
        clear its pending UI and show the fixed caption produced by the Core;
        returning handler data here could leak URLs, messages, telemetry or
        memory facts over USB.
        """

        status = str(invocation.get("status", "completed"))
        result = invocation.get("result")
        success = status == "completed" and not (isinstance(result, dict) and result.get("success") is False)
        fields: dict[str, Any] = {
            "tool_name": tool_name,
            "status": status,
            "success": success,
        }
        if call_id is not None:
            fields["call_id"] = call_id
        return server_message("tool_result", **fields)

    @staticmethod
    def _safe_result_caption(tool_name: str, result: dict[str, Any]) -> str:
        """Return a bounded, non-sensitive status for the device display.

        The handler result never crosses the device boundary. These captions
        expose only coarse, deliberately allowlisted facts so a mobile client
        can tell the user what a read-only command found without receiving
        interface names, timer labels/IDs, URLs, contacts or private text.
        """

        if result.get("success") is False:
            return "No se pudo completar la acción."
        captions = {
            "system_status": "Estado del ordenador consultado.",
            "integration_status": "Estado de integraciones consultado.",
            "system_network": "Estado de red consultado.",
            "web_search": "Búsqueda web abierta.",
            "music_open": "Apple Music abierto.",
            "music_search": "Búsqueda musical abierta; elige la pista.",
            "whatsapp_open": "WhatsApp abierto.",
            "whatsapp_compose": "Chat preparado; pulsa Enviar.",
            "whatsapp_contact": "Chat preparado; pulsa Enviar.",
            "whatsapp_contact_open": "Chat de WhatsApp abierto.",
            "whatsapp_phone_open": "Chat de WhatsApp abierto.",
            "discord_open_app": "Discord abierto.",
            "discord_open": "Canal abierto; inicia la llamada.",
            "discord_call_channel": "Canal de llamada abierto; pulsa Llamar.",
            "discord_contact": "Canal abierto; inicia la llamada.",
            "discord_call": "Canal de llamada abierto; pulsa Llamar.",
            "league_open": "League of Legends abierto.",
            "league_cancel": "Búsqueda de partida cancelada.",
            "timer_create": "Temporizador creado.",
            "timer_cancel": "Temporizador cancelado.",
            "media_action": "Control multimedia enviado.",
            "open_url": "URL abierta en el navegador.",
            "open_app": "Aplicación abierta.",
            "system_lock": "Ordenador bloqueado.",
        }
        if tool_name == "system_power":
            percent = result.get("percent")
            if result.get("available") is False:
                return "Batería no disponible en este PC."
            if isinstance(percent, int) and not isinstance(percent, bool) and 0 <= percent <= 100:
                state = "conectado a corriente" if result.get("plugged") is True else "sin corriente"
                return f"Batería: {percent}%; {state}."
            return "Estado de batería consultado."
        if tool_name == "audio_volume":
            volume = result.get("volume")
            if isinstance(volume, int) and not isinstance(volume, bool) and 0 <= volume <= 100:
                return f"Volumen: {volume}%."
        if tool_name in {"audio_mute", "audio_unmute"} and isinstance(result.get("muted"), bool):
            return "Audio silenciado." if result["muted"] else "Audio activado."
        if tool_name == "timer_list":
            timers = result.get("timers")
            if isinstance(timers, list):
                return f"Temporizadores registrados: {len(timers)}."
        if tool_name == "league_search_status":
            if result.get("supported") is False:
                return "El estado de búsqueda de League no está disponible."
            if result.get("searching") is True:
                return "League está buscando partida."
            if result.get("state") == "unknown":
                return "No se pudo confirmar el estado de búsqueda de League."
            return "League no está buscando partida."
        if tool_name == "league_status":
            search = result.get("search")
            if isinstance(search, dict):
                if search.get("searching") is True:
                    return "League está buscando partida."
                if search.get("supported") is False:
                    return "League listo; matchmaking no disponible."
            return "Estado de League consultado."
        if tool_name == "league_search":
            if result.get("already_searching"):
                return "Ya había una búsqueda activa."
            if result.get("started"):
                return "Búsqueda de partida iniciada."
        return captions.get(tool_name, "Acción completada.")
