"""Read-only checks for secure session protocol v2.

The in-memory checks use fresh identities and ephemeral keys. The separate TCP
check opens only an ephemeral loopback socket. Neither path loads or writes
the persistent DPAPI identity store or executes a real Core tool. Results are
safe to expose through local diagnostics.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from secure_audio import (
    AudioCaptureGate,
    SecureAudioCommandBridge,
    SecureAudioReceiver,
    SecureAudioSender,
    SecureAudioTranscriber,
)
from secure_core_connection import SecureCoreConnection
from secure_json_channel import SecureJsonChannel
from secure_mobile_client import SecureMobileClient
from secure_mobile_tcp_client import SecureMobileTcpClient
from secure_serial_gateway import SecureSerialGateway
from secure_session import (
    RecordError,
    SecureIdentity,
    ServerHello,
    complete_client_handshake,
    create_client_hello,
    secure_session_from_shared_secret,
)
from secure_session_server import SecureSessionServer
from secure_tcp_gateway import SecureTcpGateway

from backend.pipa_core.core import PipaCore
from backend.pipa_core.intents import parse_text_intent
from backend.pipa_core.request_binding import compute_request_digest
from backend.pipa_core.simulator import create_simulator
from backend.pipa_core.tools import ToolCatalog, ToolDefinition, ToolRouter
from tools.text_policy import validate_bounded_text

_MOBILE_INTEGRATION_CASES = (
    (
        "open_app",
        {"app": "calculator"},
        "Abrir una aplicación configurada.",
    ),
    (
        "open_codex",
        {},
        "Abrir Codex.",
    ),
    (
        "web_search",
        {"query": "documentación de diagnóstico"},
        "Buscar en Internet.",
    ),
    (
        "music_search",
        {"term": "Daft Punk"},
        "Buscar en Apple Music.",
    ),
    (
        "music_open",
        {},
        "Abrir Apple Music.",
    ),
    (
        "league_open",
        {},
        "Abrir League of Legends.",
    ),
    (
        "whatsapp_open",
        {},
        "Abrir WhatsApp Web.",
    ),
    (
        "whatsapp_compose",
        {"phone": "+34600000000", "message": "mensaje de diagnóstico"},
        "Preparar o enviar un mensaje de WhatsApp según la configuración local.",
    ),
    (
        "whatsapp_contact",
        {"contact": "contacto-diagnostico", "message": "mensaje de diagnóstico"},
        "Preparar o enviar un mensaje de WhatsApp según la configuración local.",
    ),
    (
        "whatsapp_contact_open",
        {"contact": "contacto-diagnostico"},
        "Abrir un chat de WhatsApp.",
    ),
    (
        "whatsapp_phone_open",
        {"phone": "+34600000000"},
        "Abrir un chat de WhatsApp.",
    ),
    (
        "discord_open_app",
        {},
        "Abrir Discord.",
    ),
    (
        "discord_open",
        {"channel_id": "12345678901234567", "guild_id": "98765432109876543"},
        "Abrir un canal de Discord.",
    ),
    (
        "discord_contact",
        {"contact": "contacto-diagnostico"},
        "Abrir un contacto de Discord.",
    ),
    (
        "discord_call",
        {"contact": "contacto-diagnostico"},
        "Preparar una llamada de Discord; el inicio será manual.",
    ),
    (
        "discord_call_channel",
        {"channel_id": "12345678901234567"},
        "Preparar una llamada de Discord; el inicio será manual.",
    ),
    (
        "league_search",
        {"queue": "ranked_solo"},
        "Buscar una partida en League.",
    ),
    (
        "league_cancel",
        {},
        "Cancelar la búsqueda de League.",
    ),
    (
        "system_lock",
        {},
        "Bloquear el ordenador.",
    ),
    (
        "open_url",
        {"url": "https://example.com/pipa-diagnostic"},
        "Abrir una URL validada.",
    ),
)

# These are synthetic, side-effect-free transcripts.  Keeping the expected
# intent beside the phrase makes the secure-audio diagnostic catch drift in
# the same natural-language routes used by the future device STT path.
_VOICE_INTENT_CASES = (
    ("estado de integraciones", "integration_status", {}),
    ("busca algo en internet sobre el tiempo", "web_search", {"query": "el tiempo"}),
    ("busca una canción de Daft Punk", "music_search", {"term": "Daft Punk"}),
    (
        "pon una canción de Daft Punk en Apple Music",
        "music_search",
        {"term": "Daft Punk"},
    ),
    ("busca una canción en Apple Music", "music_open", {}),
    (
        "prepara WhatsApp para +34 600 000 000 y dile llego en diez minutos",
        "whatsapp_compose",
        {"phone": "+34 600 000 000", "message": "llego en diez minutos"},
    ),
    (
        "abre WhatsApp para +34 600 000 000",
        "whatsapp_phone_open",
        {"phone": "+34 600 000 000"},
    ),
    ("abre Discord", "discord_open_app", {}),
    (
        "llama a Discord servidor 98765432109876543 canal 12345678901234567",
        "discord_call_channel",
        {"guild_id": "98765432109876543", "channel_id": "12345678901234567"},
    ),
    ("llama a amigo en Discord", "discord_call", {"contact": "amigo"}),
    (
        "manda un mensaje por WhatsApp a mamá: estoy llegando",
        "whatsapp_contact",
        {"contact": "mamá", "message": "estoy llegando"},
    ),
    ("busca una partida de ARAM", "league_search", {"queue": "aram"}),
    ("busca partida en el LoL", "league_search", {"queue": "normal_draft"}),
    ("avísame cuando encuentre una partida", "league_wait", {"seconds": 120}),
    ("cancela la búsqueda del LoL", "league_cancel", {}),
)


def _validate_voice_intent_matrix() -> int:
    """Check natural voice routes without dispatching any tool or app."""

    for transcript, expected_tool, expected_arguments in _VOICE_INTENT_CASES:
        intent = parse_text_intent(transcript)
        if intent is None or intent.tool_name != expected_tool or intent.arguments != expected_arguments:
            raise ValueError(f"voice intent matrix drifted for {expected_tool}")
    return len(_VOICE_INTENT_CASES)


def _validate_mobile_diagnostic_matrix() -> None:
    """Keep the inert mobile matrix complete with the real unsafe catalog."""

    # Import lazily so the diagnostic module remains cheap for the serial-only
    # path and never loads contact data or launches an outward adapter.
    from tools.agent_catalog import build_agent_catalog
    from tools.timers import TimerManager

    real_catalog = build_agent_catalog(TimerManager())
    real_unsafe = {name for name in real_catalog.names() if real_catalog.get(name).safety == "unsafe"}
    diagnostic_names = {tool_name for tool_name, _arguments, _summary in _MOBILE_INTEGRATION_CASES}
    if diagnostic_names != real_unsafe:
        raise ValueError("mobile diagnostic matrix is out of sync with unsafe tool catalog")
    if any(
        PipaCore._device_confirmation_summary(name) == "Confirmar acción externa."
        for name in diagnostic_names
    ):
        raise ValueError("mobile diagnostic matrix contains an unmapped device confirmation")


_DEVICE_PRIVATE_RESULT_FIELDS = frozenset(
    {
        "result",
        "url",
        "message",
        "query",
        "phone",
        "contact",
        "channel_id",
        "guild_id",
        "queue",
        "app",
        "path",
    }
)


def _device_result_has_private_fields(responses: list[dict[str, object]]) -> bool:
    """Reject private result fields while allowing safe captions such as URL."""

    return any(_DEVICE_PRIVATE_RESULT_FIELDS.intersection(response) for response in responses)


def _diagnostic_catalog(executed: list[tuple[str, dict[str, object]]]) -> ToolCatalog:
    """Build harmless stand-ins for the outward integrations.

    The real handlers are intentionally not imported here: a self-test must
    never open a browser, inspect a contact alias, or contact League Client.
    The Core still sees the real tool names and therefore exercises the same
    device-boundary confirmation policy used by production handlers.
    """

    definitions: list[ToolDefinition] = []
    for tool_name, _arguments, _summary in _MOBILE_INTEGRATION_CASES:

        def handler(
            arguments: dict[str, object],
            *,
            current_tool: str = tool_name,
        ) -> dict[str, object]:
            executed.append((current_tool, dict(arguments)))
            return {
                "success": True,
                "url": "https://private.invalid/diagnostic",
                "message": "diagnostic private payload",
            }

        def confirm_summary(
            arguments: dict[str, object],
            *,
            current_tool: str = tool_name,
        ) -> str:
            return f"{current_tool} private arguments: {arguments}"

        definitions.append(
            ToolDefinition(
                tool_name,
                handler,
                safety="unsafe",
                confirm_summary=confirm_summary,
            )
        )
    return ToolCatalog(definitions)


def _diagnostic_command_catalog() -> list[dict[str, object]]:
    """Return a bounded catalog matching the synthetic diagnostic tools."""

    return [
        {
            "id": tool_name,
            "tool_name": tool_name,
            "phrase": f"diagnóstico {tool_name}",
            "description": "Acción externa simulada; no se ejecuta ninguna integración.",
            "safety": "unsafe",
            "requires_confirmation": True,
        }
        for tool_name, _arguments, _summary in _MOBILE_INTEGRATION_CASES
    ]


def run_secure_self_test() -> dict[str, object]:
    """Exercise the authenticated handshake and encrypted JSON record layer."""

    client_identity = SecureIdentity("diagnostic-client", Ed25519PrivateKey.generate())
    server_identity = SecureIdentity("diagnostic-server", Ed25519PrivateKey.generate())
    server = SecureSessionServer(
        server_identity,
        {client_identity.identity_id: client_identity.public_key},
    )

    client_hello, client_ephemeral = create_client_hello(
        client_identity,
        session_id="diagnostic-session",
    )
    server_hello, server_session = server.accept_client_hello(client_hello.as_dict())
    client_session = complete_client_handshake(
        client_identity,
        client_hello,
        client_ephemeral,
        ServerHello(**server_hello),
        server_identity.public_key,
        expected_server_id=server_identity.identity_id,
    )

    client_channel = SecureJsonChannel(client_session)
    server_channel = SecureJsonChannel(server_session)
    request = {"protocol_version": 1, "type": "ping", "request_id": "diagnostic"}
    frame = client_channel.seal_message(request)

    tampered = dict(frame)
    ciphertext = tampered["ciphertext"]
    if not isinstance(ciphertext, str) or not ciphertext:
        raise ValueError("secure self-test produced an invalid ciphertext")
    tampered["ciphertext"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    try:
        server_channel.open_message(tampered)
    except RecordError:
        tamper_rejected = True
    else:
        raise ValueError("secure self-test accepted a tampered ciphertext")

    if server_channel.open_message(frame) != request:
        raise ValueError("secure self-test request round-trip failed")

    response = {"protocol_version": 1, "type": "pong", "request_id": "diagnostic"}
    response_frame = server_channel.seal_message(response)
    if client_channel.open_message(response_frame) != response:
        raise ValueError("secure self-test response round-trip failed")

    return {
        "handshake": True,
        "encrypted_round_trip": True,
        "tamper_rejected": tamper_rejected,
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }


def _run_synthetic_audio_bridge(
    transcript: str,
    dispatch_transcript: Callable[[str], object],
) -> dict[str, object]:
    """Run one bounded transcript through the real encrypted audio bridge.

    The PCM is synthetic and the dispatcher is injected so diagnostics can
    exercise the transport without importing or invoking outward handlers.
    """

    validated_transcript = validate_bounded_text(transcript, "La transcripción", 4000).strip()
    shared_secret = bytes(range(1, 33))
    transcript_hash = bytes(range(32, 64))
    sender_session = secure_session_from_shared_secret(
        "audio-diagnostic",
        shared_secret,
        transcript_hash,
        role="client",
    )
    receiver_session = secure_session_from_shared_secret(
        "audio-diagnostic",
        shared_secret,
        transcript_hash,
        role="server",
    )
    routed_transcripts: list[str] = []
    bridge: SecureAudioCommandBridge | None = None
    try:
        sender = SecureAudioSender(sender_session, "diagnostic-stream")
        first = sender.seal_chunk(b"\x01\x02" * 8, final=False)
        final = sender.seal_chunk(b"\x03\x04" * 8, final=True)
        gate = AudioCaptureGate()
        if not gate.mark_codec_ready(True):
            raise ValueError("secure audio diagnostic could not enter codec-ready state")

        received_bytes = 0

        def transcribe(chunk: memoryview, is_final: bool) -> str | None:
            nonlocal received_bytes
            received_bytes += len(chunk)
            return validated_transcript if is_final else None

        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(receiver_session),
            transcribe,
            gate,
        )

        def route_transcript(transcript: str) -> list[dict[str, object]]:
            routed_transcripts.append(transcript)
            dispatch_transcript(transcript)
            return []

        bridge = SecureAudioCommandBridge(transcriber, route_transcript)
        bridge.begin_capture(
            display_ready=True,
            consented=True,
            secure_transport_ready=True,
        )
        if bridge.consume_frame(first):
            raise ValueError("secure audio diagnostic marked a non-final chunk as final")
        if not bridge.consume_frame(final):
            raise ValueError("secure audio diagnostic did not finish the stream")
        summary, routed = bridge.finalize()
        if (
            received_bytes != 32
            or summary.stream_bytes != 32
            or summary.stream_duration_ms != 1
            or gate.can_capture
            or routed_transcripts != [validated_transcript]
            or routed != []
        ):
            raise ValueError("secure audio diagnostic returned an invalid transcript path")
    finally:
        if bridge is not None:
            bridge.close()
        sender_session.close()
        receiver_session.close()

    return {
        "transcript": validated_transcript,
        "stream_bytes": summary.stream_bytes,
        "stream_duration_ms": summary.stream_duration_ms,
        "transcript_count": len(routed_transcripts),
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }


def preview_secure_audio_transcript(transcript: str) -> dict[str, object]:
    """Validate one synthetic voice transcript without dispatching a tool."""

    result = _run_synthetic_audio_bridge(transcript, lambda _transcript: None)
    return {
        "transcript": result["transcript"],
        "stream_bytes": result["stream_bytes"],
        "stream_duration_ms": result["stream_duration_ms"],
        "secure_audio_round_trip": True,
        "audio_captured": False,
        "hardware_required": True,
        "side_effects": False,
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }


def run_secure_audio_self_test() -> dict[str, object]:
    """Exercise bounded encrypted audio with synthetic samples only.

    The check proves the future capture path still needs codec readiness,
    visible consent and an ordered encrypted stream, without opening a
    microphone, socket or serial port. It also routes a safe transcript
    through the Core and checks representative integration phrases so the
    voice bridge cannot drift from text handling.
    """

    voice_intents_checked = _validate_voice_intent_matrix()
    core = PipaCore(
        verifier=object(),
        router=ToolRouter(
            ToolCatalog(
                [
                    ToolDefinition(
                        "integration_status",
                        lambda _arguments: {"success": True, "simulated": True},
                    )
                ]
            )
        ),
    )
    session = core.sessions.create(
        "audio-diagnostic-device",
        capabilities=("display", "touch"),
        capabilities_initialized=True,
    )
    routed: list[list[dict[str, object]]] = []
    try:
        _run_synthetic_audio_bridge(
            "estado de integraciones",
            lambda transcript: routed.append(core.handle_transcript(session.session_id, transcript)),
        )
        routed_result = next(
            (item for item in routed[0] if item.get("type") == "tool_result"),
            None,
        )
        if routed_result is None or routed_result.get("tool_name") != "integration_status":
            raise ValueError("secure audio diagnostic did not route the transcript through Core")
    finally:
        core.close(session.session_id)

    return {
        "encrypted_round_trip": True,
        "capture_gate": True,
        "ordered_stream": True,
        "bounded_summary": True,
        "transcript_bridge": True,
        "intent_routed": True,
        "voice_intents_checked": voice_intents_checked,
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }


def run_device_protocol_self_test() -> dict[str, object]:
    """Exercise the v1 device lifecycle with inert handlers only.

    This is the closest pre-hardware check for the ordinary Waveshare path:
    an ephemeral device authenticates, sends text, receives a physical-style
    confirmation and completes the action. A second device without touch is
    also checked to ensure an external action is rejected before a pending
    confirmation can be created.
    """

    executed: list[tuple[str, dict[str, object]]] = []

    def safe_handler(_arguments: dict[str, object]) -> dict[str, object]:
        return {"success": True, "simulated": True}

    def external_handler(arguments: dict[str, object]) -> dict[str, object]:
        executed.append(("web_search", dict(arguments)))
        return {
            "success": True,
            "url": "https://private.invalid/diagnostic",
            "query": arguments.get("query"),
        }

    catalog = ToolCatalog(
        [
            ToolDefinition("system_status", safe_handler),
            ToolDefinition(
                "web_search",
                external_handler,
                safety="unsafe",
                confirm_summary=lambda _arguments: "Buscar en Internet.",
            ),
        ]
    )
    simulator = create_simulator(catalog, capabilities=("display", "touch"))
    try:
        safe_result = simulator.send(
            "text_input",
            text="estado del ordenador",
            source="voice",
        )
        if not any(item.get("type") == "tool_result" for item in safe_result):
            raise ValueError("v1 simulator did not execute a safe text command")

        pending = simulator.send(
            "text_input",
            text="busca en internet diagnóstico de Pipa",
            source="voice",
        )
        confirmation = next(
            (item for item in pending if item.get("type") == "confirm_request"),
            None,
        )
        if confirmation is None or confirmation.get("summary") != "Buscar en Internet.":
            raise ValueError("v1 simulator did not create the fixed confirmation")
        if executed:
            raise ValueError("v1 simulator executed before confirmation")
        completed = simulator.send(
            "confirm",
            confirmation_id=confirmation["confirmation_id"],
            accepted=True,
        )
        result = next((item for item in completed if item.get("type") == "tool_result"), None)
        if result is None or "result" in result or "url" in str(result) or "diagnóstico" in str(result):
            raise ValueError("v1 simulator leaked an external result")
    finally:
        simulator.close()

    no_touch = create_simulator(catalog, capabilities=("display",))
    try:
        unavailable = no_touch.send(
            "tool_call",
            name="web_search",
            arguments={"query": "diagnóstico sin touch"},
        )
        if not any(item.get("code") == "confirmation_unavailable" for item in unavailable):
            raise ValueError("v1 simulator allowed an unsafe action without touch")
    finally:
        no_touch.close()

    if executed != [("web_search", {"query": "diagnóstico de Pipa"})]:
        raise ValueError("v1 simulator executed an unexpected action")
    return {
        "authenticated": True,
        "safe_text_command": True,
        "confirmation_gated": True,
        "missing_touch_rejected": True,
        "result_redacted": True,
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }


def run_mobile_protocol_self_test() -> dict[str, object]:
    """Exercise the future mobile profile without sockets or external tools."""

    _validate_mobile_diagnostic_matrix()
    mobile_identity = SecureIdentity("mobile-diagnostic", Ed25519PrivateKey.generate())
    server_identity = SecureIdentity("server-diagnostic", Ed25519PrivateKey.generate())
    executed: list[tuple[str, dict[str, object]]] = []
    catalog = _diagnostic_catalog(executed)
    core = PipaCore(
        verifier=object(),
        router=ToolRouter(catalog),
        command_catalog=_diagnostic_command_catalog,
        capability_catalog=lambda: {
            "web_search": {"available": True},
            "apple_music": {"available": True, "playback": False},
        },
    )
    connection = SecureCoreConnection(
        core,
        server_identity,
        {mobile_identity.identity_id: mobile_identity.public_key},
    )
    client = SecureMobileClient(
        mobile_identity,
        server_identity.public_key,
        server_id=server_identity.identity_id,
    )
    try:
        hello = client.connect(connection)
        if len(hello) != 1 or hello[0].get("type") != "device_hello_ack":
            raise ValueError("mobile capability announcement was not acknowledged")
        details = client.request_catalog_details()
        if details["capabilities"] != {
            "web_search": {"available": True},
            "apple_music": {"available": True, "playback": False},
        }:
            raise ValueError("mobile capability matrix was not bounded")
        if len(details["commands"]) != len(_MOBILE_INTEGRATION_CASES):
            raise ValueError("mobile diagnostic catalog was not complete")
        for index, (tool_name, arguments, expected_summary) in enumerate(_MOBILE_INTEGRATION_CASES):
            executed_before = len(executed)
            pending = client.call_tool(tool_name, arguments, call_id=f"diagnostic-{index}")
            if len(pending) != 2 or pending[0].get("type") != "confirm_request":
                raise ValueError("mobile tool call did not reach confirmation")
            if pending[0].get("summary") != expected_summary:
                raise ValueError("mobile confirmation summary was not fixed")
            if pending[0].get("request_digest") != compute_request_digest(tool_name, arguments):
                raise ValueError("mobile confirmation request binding was not preserved")
            pending_text = str(pending)
            if any(str(value) in pending_text for value in arguments.values()):
                raise ValueError("mobile confirmation echoed private arguments")
            if len(executed) != executed_before:
                raise ValueError("mobile diagnostic executed before confirmation")
            completed = client.confirm(str(pending[0]["confirmation_id"]), True)
            if len(completed) != 2 or completed[0].get("type") != "tool_result":
                raise ValueError("mobile confirmation did not complete")
            if _device_result_has_private_fields(completed) or any(
                str(value) in str(completed) for value in arguments.values()
            ):
                raise ValueError("mobile result crossed the safe boundary")
        if len(executed) != len(_MOBILE_INTEGRATION_CASES):
            raise ValueError("mobile diagnostic actions were not completed after confirmation")
    finally:
        client.close()

    return {
        "handshake": True,
        "capabilities_acknowledged": True,
        "confirmation_gated": True,
        "request_binding": True,
        "result_redacted": True,
        "integration_tools_checked": len(_MOBILE_INTEGRATION_CASES),
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }


def run_mobile_tcp_self_test() -> dict[str, object]:
    """Exercise the real loopback TCP adapter without persistent state."""

    _validate_mobile_diagnostic_matrix()

    async def exercise() -> dict[str, object]:
        mobile_identity = SecureIdentity("mobile-tcp-diagnostic", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("server-tcp-diagnostic", Ed25519PrivateKey.generate())
        executed: list[tuple[str, dict[str, object]]] = []
        catalog = _diagnostic_catalog(executed)
        core = PipaCore(
            verifier=object(),
            router=ToolRouter(catalog),
            command_catalog=_diagnostic_command_catalog,
            capability_catalog=lambda: {
                "web_search": {"available": True},
                "discord": {"available": True, "start_call": False},
            },
        )
        gateway = SecureTcpGateway(
            core,
            "127.0.0.1",
            0,
            server_identity,
            {mobile_identity.identity_id: mobile_identity.public_key},
        )
        gateway.start()
        client = SecureMobileTcpClient(
            mobile_identity,
            server_identity.public_key,
            server_id=server_identity.identity_id,
        )
        try:
            hello = await client.connect(gateway.bind_host, gateway.port)
            if len(hello) != 1 or hello[0].get("type") != "device_hello_ack":
                raise ValueError("TCP mobile capability announcement was not acknowledged")
            details = await client.request_catalog_details()
            commands = details["commands"]
            if len(commands) != len(_MOBILE_INTEGRATION_CASES) or any(
                "result" in command for command in commands
            ):
                raise ValueError("TCP mobile catalog was not bounded")
            if details["capabilities"] != {
                "web_search": {"available": True},
                "discord": {"available": True, "start_call": False},
            }:
                raise ValueError("TCP mobile capability matrix was not bounded")
            for index, (tool_name, arguments, expected_summary) in enumerate(_MOBILE_INTEGRATION_CASES):
                pending = await client.call_tool(tool_name, arguments, call_id=f"tcp-diagnostic-{index}")
                if len(pending) != 2 or pending[0].get("type") != "confirm_request":
                    raise ValueError("TCP mobile tool call did not reach confirmation")
                if pending[0].get("summary") != expected_summary:
                    raise ValueError("TCP mobile confirmation summary was not fixed")
                if pending[0].get("request_digest") != compute_request_digest(tool_name, arguments):
                    raise ValueError("TCP mobile confirmation request binding was not preserved")
                pending_text = str(pending)
                if any(str(value) in pending_text for value in arguments.values()):
                    raise ValueError("TCP mobile confirmation echoed private arguments")
                if len(executed) != index:
                    raise ValueError("TCP mobile diagnostic executed before confirmation")
                completed = await client.confirm(str(pending[0]["confirmation_id"]), True)
                if len(completed) != 2 or completed[0].get("type") != "tool_result":
                    raise ValueError("TCP mobile confirmation did not complete")
                if _device_result_has_private_fields(completed) or any(
                    str(value) in str(completed) for value in arguments.values()
                ):
                    raise ValueError("TCP mobile result crossed the safe boundary")
            if len(executed) != len(_MOBILE_INTEGRATION_CASES):
                raise ValueError("TCP mobile diagnostic actions were not completed after confirmation")
        finally:
            await client.close()
            gateway.stop()

        return {
            "listener_loopback_only": gateway.bind_host == "127.0.0.1",
            "network_round_trip": True,
            "confirmation_gated": True,
            "request_binding": True,
            "result_redacted": True,
            "integration_tools_checked": len(_MOBILE_INTEGRATION_CASES),
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

    return asyncio.run(exercise())


class _DiagnosticSerialConnection:
    """Bounded in-memory serial endpoint used by the diagnostics only.

    It deliberately implements the tiny interface consumed by the gateway
    instead of importing pyserial or opening a device path. The callback
    drives the client side of the real encrypted protocol, so the check still
    exercises framing, handshake, Core routing, confirmation and redaction.
    """

    def __init__(self, gateway: SecureSerialGateway, first_line: bytes) -> None:
        self.gateway = gateway
        self.lines = [first_line]
        self.writes: list[bytes] = []
        self.client_channel: SecureJsonChannel | None = None
        self.client_identity: SecureIdentity | None = None
        self.client_hello: Any = None
        self.client_ephemeral: Any = None
        self.server_identity: SecureIdentity | None = None
        self.received: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read_until(self, _separator: bytes, _size: int) -> bytes:
        if self.lines:
            return self.lines.pop(0)
        self.gateway._stop.set()
        return b""

    def write(self, value: bytes) -> None:
        self.writes.append(value)
        payload = json.loads(value.decode("utf-8"))
        if self.client_channel is None:
            if (
                self.client_identity is None
                or self.server_identity is None
                or self.client_hello is None
                or self.client_ephemeral is None
            ):
                raise AssertionError("diagnostic serial handshake state is incomplete")
            client_session = complete_client_handshake(
                self.client_identity,
                self.client_hello,
                self.client_ephemeral,
                ServerHello(**payload),
                self.server_identity.public_key,
            )
            self.client_channel = SecureJsonChannel(client_session)
            self._queue(
                {
                    "protocol_version": 1,
                    "type": "device_hello",
                    "firmware_version": "diagnostic-device",
                    "capabilities": ["display", "touch", "text_input"],
                }
            )
            return

        message = self.client_channel.open_message(payload)
        self.received.append(message)
        message_type = message.get("type")
        if message_type == "device_hello_ack":
            self._queue(
                {
                    "protocol_version": 1,
                    "type": "catalog_request",
                }
            )
        elif message_type == "catalog":
            if any("result" in command for command in message.get("commands", [])):
                raise AssertionError("serial diagnostic catalog leaked a result field")
            self._queue(
                {
                    "protocol_version": 1,
                    "type": "tool_call",
                    "name": "web_search",
                    "arguments": {"query": "diagnóstico de Pipa"},
                    "call_id": "serial-diagnostic-tool",
                }
            )
        elif message_type == "confirm_request":
            if message.get("summary") != "Buscar en Internet.":
                raise AssertionError("serial diagnostic confirmation was not fixed")
            self._queue(
                {
                    "protocol_version": 1,
                    "type": "confirm",
                    "confirmation_id": message["confirmation_id"],
                    "accepted": True,
                }
            )
        elif message_type == "tool_result":
            if "result" in message or "url" in message or "query" in message:
                raise AssertionError("serial diagnostic result crossed the device boundary")
            self.gateway._stop.set()

    def reset_input_buffer(self) -> None:
        self.lines.clear()

    def _queue(self, message: dict[str, object]) -> None:
        if self.client_channel is None:
            raise AssertionError("diagnostic serial channel is not ready")
        self.lines.append(
            (json.dumps(self.client_channel.seal_message(message), separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
        )


def run_secure_serial_self_test() -> dict[str, object]:
    """Exercise the complete encrypted serial adapter without hardware."""

    client_identity = SecureIdentity("serial-diagnostic-client", Ed25519PrivateKey.generate())
    server_identity = SecureIdentity("serial-diagnostic-server", Ed25519PrivateKey.generate())
    executed: list[tuple[str, dict[str, object]]] = []
    core = PipaCore(
        verifier=object(),
        router=ToolRouter(_diagnostic_catalog(executed)),
        command_catalog=_diagnostic_command_catalog,
        capability_catalog=lambda: {"web_search": {"available": True}},
    )
    gateway = SecureSerialGateway(
        core,
        "COM7",
        server_identity,
        {client_identity.identity_id: client_identity.public_key},
    )
    gateway._stop.clear()
    client_hello, client_ephemeral = create_client_hello(
        client_identity,
        session_id="serial-diagnostic-session",
    )
    connection = _DiagnosticSerialConnection(
        gateway,
        (json.dumps(client_hello.as_dict(), separators=(",", ":")) + "\n").encode("utf-8"),
    )
    connection.client_identity = client_identity
    connection.client_hello = client_hello
    connection.client_ephemeral = client_ephemeral
    connection.server_identity = server_identity
    try:
        gateway._serve_connection(connection)
    finally:
        gateway._stop.clear()

    if connection.client_channel is None or len(connection.writes) < 5:
        raise ValueError("secure serial loopback did not complete")
    if executed != [("web_search", {"query": "diagnóstico de Pipa"})]:
        raise ValueError("secure serial loopback executed an unexpected action")
    if not any(message.get("type") == "tool_result" for message in connection.received):
        raise ValueError("secure serial loopback did not return a tool result")
    return {
        "handshake": True,
        "encrypted_round_trip": True,
        "catalog_bounded": True,
        "confirmation_gated": True,
        "result_redacted": True,
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }
