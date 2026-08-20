"""Opt-in encrypted USB-serial gateway for secure session protocol v2.

The normal gateway remains the v1 compatibility transport. This worker is
selected only when ``PIPA_SERIAL_SECURITY=v2`` is explicitly configured. It
never falls back to v1 on the same connection: a failed secure handshake is a
closed connection, which prevents a downgrade through the serial port.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from pipa_serial_gateway import MAX_LINE_BYTES, SerialGateway, is_serial_diagnostic
from secure_audio import (
    AudioCaptureGate,
    AudioFrameError,
    SecureAudioCommandBridge,
    SecureAudioReceiver,
    SecureAudioTranscriber,
    is_secure_audio_frame,
)
from secure_core_connection import SecureCoreConnection
from secure_identity_store import (
    SecureIdentityStore,
    SecureIdentityStoreError,
    default_secure_identity_path,
)
from secure_session import HandshakeError, SecureIdentity, SecureSessionError
from secure_session_server import SecureSessionServer
from trusted_unlock_devices import WindowsRegistryDeviceStore
from voice_diagnostics import VoiceDiagnosticStore

from backend.pipa_core.connection import AUTHENTICATION_TIMEOUT_SECONDS, SESSION_IDLE_SECONDS
from backend.pipa_core.core import PipaCore

LOGGER = logging.getLogger("pipa.secure-serial")
SECURE_SECURITY_MODE = "v2"
DEFAULT_SERVER_ID = "pipa-agent-v2"
DEFAULT_REVOCATION_CHECK_SECONDS = 5.0
_CLIENT_HELLO_FIELDS = frozenset(
    {
        "client_ephemeral_public_key",
        "client_id",
        "client_nonce",
        "protocol_version",
        "session_id",
        "signature",
    }
)
_SEALED_FRAME_FIELDS = frozenset({"ciphertext", "protocol_version", "sequence", "session_id"})
_SESSION_RESET_HINT = {"protocol_version": 2, "type": "session_reset"}


class _SecureSerialAudioRuntime:
    """Bind one consented audio stream to the authenticated Core session."""

    def __init__(
        self,
        connection: SecureCoreConnection,
        provider_factory: Callable[[], Any],
        diagnostic_recorder: Callable[[str, Mapping[str, object] | None, list[dict[str, object]]], None],
    ) -> None:
        self.connection = connection
        self.provider_factory = provider_factory
        self.diagnostic_recorder = diagnostic_recorder
        self.bridge: SecureAudioCommandBridge | None = None

    def begin(self) -> None:
        if self.bridge is not None:
            raise AudioFrameError("audio capture is already active")
        session_id = self.connection.core_session_id
        secure_session = self.connection.secure_session
        core_session = self.connection.core.sessions.get(session_id) if session_id is not None else None
        if (
            session_id is None
            or secure_session is None
            or core_session is None
            or core_session.state != "listening"
            or "display" not in core_session.capabilities
            or "audio_capture" not in core_session.capabilities
            or core_session.audio_state != "codec_ready"
        ):
            raise AudioFrameError("audio capture capability is not ready")

        provider = self.provider_factory()
        reset_provider = getattr(provider, "reset", None)
        gate = AudioCaptureGate()
        if not gate.mark_codec_ready(True):
            raise AudioFrameError("audio capture gate is not ready")
        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(secure_session),
            provider,
            gate,
            reset_provider=reset_provider if callable(reset_provider) else None,
        )

        def dispatch(transcript: str):
            messages = self.connection.core.handle_transcript(session_id, transcript)
            metadata = getattr(provider, "diagnostics", None)
            if transcript:
                self.diagnostic_recorder(
                    transcript,
                    metadata if isinstance(metadata, Mapping) else None,
                    messages,
                )
            return messages

        bridge = SecureAudioCommandBridge(transcriber, dispatch)
        bridge.begin_capture(display_ready=True, consented=True, secure_transport_ready=True)
        self.bridge = bridge

    def consume(self, frame: Mapping[str, Any]) -> list[dict[str, object]]:
        bridge = self.bridge
        if bridge is None:
            raise AudioFrameError("audio frame arrived without visible consent")
        final = bridge.consume_frame(frame)
        if not final:
            return []
        try:
            _summary, messages = bridge.finalize()
        finally:
            self.bridge = None
        if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
            raise AudioFrameError("audio transcript returned invalid Core messages")
        return self.connection.seal_messages(messages)

    def cancel(self) -> None:
        bridge = self.bridge
        self.bridge = None
        if bridge is not None:
            bridge.close(close_session=False)

    def close(self) -> None:
        bridge = self.bridge
        self.bridge = None
        if bridge is not None:
            bridge.close()


class SecureSerialGateway(SerialGateway):
    """Serve one encrypted v2 serial connection without a downgrade path."""

    def __init__(
        self,
        core: PipaCore,
        port: str,
        server_identity: SecureIdentity,
        trusted_devices: Mapping[str, Any],
        *,
        baudrate: int = 115200,
        trusted_devices_provider: Callable[[], Mapping[str, Any]] | None = None,
        speech_provider_factory: Callable[[], Any] | None = None,
        revocation_check_seconds: float = DEFAULT_REVOCATION_CHECK_SECONDS,
    ) -> None:
        super().__init__(core, port, baudrate=baudrate)
        if trusted_devices_provider is not None and not callable(trusted_devices_provider):
            raise TypeError("trusted_devices_provider must be callable")
        if not 0.1 <= revocation_check_seconds <= 60:
            raise ValueError("revocation_check_seconds is outside the safe range")
        self.server_identity = server_identity
        self.trusted_devices = dict(trusted_devices)
        self.session_server = SecureSessionServer(server_identity, self.trusted_devices)
        self.trusted_devices_provider = trusted_devices_provider
        self.revocation_check_seconds = revocation_check_seconds
        if speech_provider_factory is not None and not callable(speech_provider_factory):
            raise TypeError("speech_provider_factory must be callable")
        self.speech_provider_factory = speech_provider_factory
        self._voice_ready = threading.Event()
        self._local_wake_phrase_ready = threading.Event()
        self._voice_diagnostic_store = VoiceDiagnosticStore()

    @property
    def voice_enabled(self) -> bool:
        return self.speech_provider_factory is not None

    @property
    def voice_ready(self) -> bool:
        return self._voice_ready.is_set()

    @property
    def local_wake_phrase_ready(self) -> bool:
        return self._local_wake_phrase_ready.is_set()

    def voice_diagnostics(self) -> dict[str, object]:
        result = self._voice_diagnostic_store.snapshot()
        result["voice_enabled"] = self.voice_enabled
        result["voice_ready"] = self.voice_ready
        result["local_wake_phrase_ready"] = self.local_wake_phrase_ready
        return result

    def _record_voice_diagnostic(
        self,
        transcript: str,
        stt_metadata: Mapping[str, object] | None,
        messages: list[dict[str, object]],
    ) -> None:
        self._voice_diagnostic_store.record(
            transcript,
            stt_metadata=stt_metadata,
            messages=messages,
        )

    def _serve_connection(self, connection) -> None:
        secure_core = SecureCoreConnection(
            self.core,
            self.server_identity,
            self.trusted_devices,
            session_server=self.session_server,
        )
        last_activity = time.monotonic()
        last_trust_check = 0.0
        audio_runtime: _SecureSerialAudioRuntime | None = None
        rehandshake_requested = False
        line_buffer = bytearray()
        try:
            self._refresh_trusted_devices()
            while not self._stop.is_set():
                idle_limit = (
                    SESSION_IDLE_SECONDS if secure_core.authenticated else AUTHENTICATION_TIMEOUT_SECONDS
                )
                if time.monotonic() - last_activity >= idle_limit:
                    LOGGER.warning("secure serial connection timed out")
                    break
                if (
                    secure_core.authenticated
                    and time.monotonic() - last_trust_check >= self.revocation_check_seconds
                ):
                    self._refresh_trusted_devices()
                    last_trust_check = time.monotonic()
                    if not secure_core.device_is_trusted():
                        LOGGER.warning("secure serial device was revoked")
                        break
                fragment = connection.read_until(
                    b"\n",
                    MAX_LINE_BYTES + 1 - len(line_buffer),
                )
                if not fragment:
                    continue
                line_buffer.extend(fragment)
                if len(line_buffer) > MAX_LINE_BYTES:
                    line_buffer.clear()
                    connection.reset_input_buffer()
                    LOGGER.warning("secure serial message exceeded the configured limit")
                    break
                if not line_buffer.endswith(b"\n"):
                    continue
                raw = bytes(line_buffer)
                line_buffer.clear()
                if is_serial_diagnostic(raw):
                    continue
                try:
                    payload = _strict_json(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    first_byte = raw[0] if raw else -1
                    LOGGER.warning(
                        "secure serial message was not valid JSON "
                        "(bytes=%d, first=0x%02x, newline=%s, nul=%s)",
                        len(raw),
                        first_byte,
                        True,
                        b"\x00" in raw,
                    )
                    break

                if not secure_core.authenticated:
                    if set(payload) != _CLIENT_HELLO_FIELDS or payload.get("protocol_version") != 2:
                        if not rehandshake_requested and _is_stale_secure_frame(payload):
                            # A restarted Windows agent has intentionally lost
                            # the previous ephemeral keys, while the device can
                            # still be sending records from that old session.
                            # Ask the physically attached device to start a new
                            # signed handshake; never reinterpret the record or
                            # fall back to v1.
                            self._send(connection, _SESSION_RESET_HINT)
                            rehandshake_requested = True
                            continue
                        LOGGER.warning("secure serial connection did not start with ClientHello")
                        break
                    try:
                        server_hello = secure_core.accept_client_hello(payload)
                    except (HandshakeError, SecureSessionError, ValueError):
                        LOGGER.warning("secure serial ClientHello was rejected")
                        break
                    self._send(connection, server_hello)
                    if self.speech_provider_factory is not None:
                        audio_runtime = _SecureSerialAudioRuntime(
                            secure_core,
                            self.speech_provider_factory,
                            self._record_voice_diagnostic,
                        )
                    last_activity = time.monotonic()
                    # Force one immediate post-handshake check before the
                    # first encrypted application frame is accepted.
                    last_trust_check = 0.0
                    continue

                try:
                    if is_secure_audio_frame(payload):
                        if audio_runtime is None:
                            raise AudioFrameError("secure audio is disabled")
                        responses = audio_runtime.consume(payload)
                    else:
                        responses = secure_core.process_frame(payload)
                        self._update_voice_ready(secure_core)
                        if secure_core.last_message_type == "confirm":
                            self._voice_diagnostic_store.update_from_messages(secure_core.last_core_responses)
                        if secure_core.last_message_type == "hold_start":
                            if audio_runtime is None:
                                raise AudioFrameError("secure audio is disabled")
                            audio_runtime.begin()
                        elif secure_core.last_message_type == "abort" and audio_runtime is not None:
                            audio_runtime.cancel()
                except (AudioFrameError, SecureSessionError):
                    LOGGER.warning("secure serial encrypted frame was rejected")
                    break
                last_activity = time.monotonic()
                for response in responses:
                    self._send(connection, response)
        except Exception:
            LOGGER.error("unexpected secure serial gateway error", exc_info=True)
        finally:
            self._voice_ready.clear()
            self._local_wake_phrase_ready.clear()
            if audio_runtime is not None:
                audio_runtime.close()
            secure_core.close()

    def _update_voice_ready(self, connection: SecureCoreConnection) -> None:
        session_id = connection.core_session_id
        core_session = self.core.sessions.get(session_id) if session_id is not None else None
        ready = bool(
            self.speech_provider_factory is not None
            and core_session is not None
            and "display" in core_session.capabilities
            and "audio_capture" in core_session.capabilities
            and core_session.audio_state == "codec_ready"
        )
        if ready:
            self._voice_ready.set()
        else:
            self._voice_ready.clear()
        if core_session is not None and "local_wake_phrase" in core_session.capabilities:
            self._local_wake_phrase_ready.set()
        else:
            self._local_wake_phrase_ready.clear()

    def _refresh_trusted_devices(self) -> None:
        provider = self.trusted_devices_provider
        if provider is None:
            return
        current = provider()
        if not isinstance(current, Mapping):
            raise ValueError("secure serial trust provider returned an invalid mapping")
        self.session_server.refresh_trusted_devices(current)

    @staticmethod
    def _send(connection, payload: dict[str, Any]) -> None:
        """Send only a v2 frame; never emit the v1 error fallback."""

        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_LINE_BYTES:
            LOGGER.error("secure serial response exceeded the configured limit")
            return
        connection.write(encoded)


def _is_stale_secure_frame(payload: Mapping[str, Any]) -> bool:
    """Recognize only a v2 record left by an earlier local agent session."""

    return payload.get("protocol_version") == 2 and (
        set(payload) == _SEALED_FRAME_FIELDS or is_secure_audio_frame(payload)
    )


def start_configured_secure_gateway(core: PipaCore) -> SecureSerialGateway | None:
    """Create the explicitly requested v2 gateway, failing closed on setup errors."""

    port = os.environ.get("PIPA_SERIAL_PORT", "").strip()
    if not port:
        return None
    server_id = os.environ.get("PIPA_SECURE_SERVER_ID", DEFAULT_SERVER_ID).strip()
    try:
        voice_setting = os.environ.get("PIPA_VOICE_ENABLED", "0").strip()
        if voice_setting not in {"0", "1"}:
            raise ValueError("PIPA_VOICE_ENABLED must be 0 or 1")
        speech_provider_factory = None
        if voice_setting == "1":
            from local_stt import LocalSpeechTranscriber

            speech_provider_factory = LocalSpeechTranscriber
        baudrate = int(os.environ.get("PIPA_SERIAL_BAUDRATE", "115200"))
        # Provisioning is an explicit administrative action. The running
        # agent must never create a new identity merely because v2 was
        # enabled; doing so would make a typo or an unpaired device mutate
        # the trust root at startup.
        server_identity = SecureIdentityStore(default_secure_identity_path()).load(server_id)
        device_store = WindowsRegistryDeviceStore()
        trusted_devices = device_store.trusted_public_keys()
        if not trusted_devices:
            raise ValueError("no Pipa devices are paired for secure serial")
        gateway = SecureSerialGateway(
            core,
            port,
            server_identity,
            trusted_devices,
            baudrate=baudrate,
            trusted_devices_provider=device_store.trusted_public_keys,
            speech_provider_factory=speech_provider_factory,
        )
        gateway.start()
        LOGGER.info("Pipa secure serial gateway enabled")
        return gateway
    except (SecureIdentityStoreError, TypeError, ValueError):
        LOGGER.error("Could not configure the secure Pipa serial gateway")
        return None
    except Exception:
        LOGGER.error("Could not configure the secure Pipa serial gateway")
        return None


def _strict_json(raw: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("secure serial frame must be an object")
    return value
