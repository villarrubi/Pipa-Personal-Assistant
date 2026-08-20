"""In-memory opt-in v2 adapter between SecureJsonChannel and PipaCore."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from secure_json_channel import SecureJsonChannel
from secure_session import HandshakeError, SecureIdentity, SecureSessionError
from secure_session_server import SecureSessionServer

from backend.pipa_core.core import PipaCore
from backend.pipa_core.protocol import ProtocolError, parse_client_message, server_message
from backend.pipa_core.state import SessionLimitError

MAX_SECURE_PROTOCOL_ERRORS = 3


class SecureCoreConnectionError(SecureSessionError):
    """The opt-in v2 Core adapter cannot continue safely."""


class SecureCoreConnection:
    """Route decrypted v1 Core messages through an authenticated v2 session.

    This class has no network code. A transport adapter provides the outer
    JSON frames and uses this class without duplicating handshake,
    replay, encryption, or Core lifecycle logic.
    """

    def __init__(
        self,
        core: PipaCore,
        server_identity: SecureIdentity,
        trusted_devices: Mapping[str, Any],
        *,
        session_server: SecureSessionServer | None = None,
    ) -> None:
        if not isinstance(core, PipaCore):
            raise TypeError("core must be PipaCore")
        self.core = core
        if session_server is not None and not isinstance(session_server, SecureSessionServer):
            raise TypeError("session_server must be SecureSessionServer")
        self.server = session_server or SecureSessionServer(server_identity, trusted_devices)
        self._channel: SecureJsonChannel | None = None
        self._core_session_id: str | None = None
        self._device_id: str | None = None
        self._device_public_key = None
        self._protocol_errors = 0
        self._last_message_type: str | None = None

    @property
    def authenticated(self) -> bool:
        return self._channel is not None and self._core_session_id is not None

    @property
    def core_session_id(self) -> str | None:
        return self._core_session_id

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def secure_session(self):
        channel = self._channel
        return channel.session if channel is not None else None

    @property
    def last_message_type(self) -> str | None:
        return self._last_message_type

    def device_is_trusted(self) -> bool:
        """Return whether this session's paired key is still current."""

        if self._device_id is None or self._device_public_key is None:
            return False
        return self.server.is_trusted_device(self._device_id, self._device_public_key)

    def accept_client_hello(
        self,
        payload: Mapping[str, Any],
        *,
        firmware_version: str | None = None,
        capabilities: tuple[str, ...] = (),
    ) -> dict[str, object]:
        if self.authenticated:
            raise SecureCoreConnectionError("secure Core connection is already authenticated")
        server_payload, secure_session = self.server.accept_client_hello(payload)
        device_id = str(server_payload["client_id"])
        client_public_key = self.server.trusted_device_public_key(device_id)
        if client_public_key is None:
            secure_session.close()
            raise HandshakeError("client identity is no longer paired")
        try:
            core_session = self.core.sessions.create(
                device_id,
                firmware_version=firmware_version,
                capabilities=capabilities,
                capabilities_initialized=False,
            )
        except SessionLimitError as error:
            secure_session.close()
            raise HandshakeError("Core session limit reached") from error
        self._channel = SecureJsonChannel(secure_session)
        self._core_session_id = core_session.session_id
        self._device_id = device_id
        self._device_public_key = client_public_key
        return server_payload

    def process_frame(self, frame: Mapping[str, Any]) -> list[dict[str, object]]:
        channel = self._channel
        session_id = self._core_session_id
        self._last_message_type = None
        if channel is None or session_id is None:
            raise SecureCoreConnectionError("secure Core connection is not authenticated")
        if not self.device_is_trusted():
            self.close()
            raise HandshakeError("client identity is no longer paired")
        try:
            payload = channel.open_message(frame)
        except SecureSessionError:
            self.close()
            raise
        try:
            message = parse_client_message(payload)
        except ProtocolError:
            self._protocol_errors += 1
            response = channel.seal_message(server_message("error", code="protocol_error"))
            if self._protocol_errors >= MAX_SECURE_PROTOCOL_ERRORS:
                self.close()
            return [response]

        self._protocol_errors = 0
        self._last_message_type = message.type
        responses = self.core.handle(session_id, message)
        return [channel.seal_message(response) for response in responses]

    def seal_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, object]]:
        """Seal trusted Core responses after an authenticated audio stream."""

        channel = self._channel
        if channel is None or self._core_session_id is None or not self.device_is_trusted():
            raise SecureCoreConnectionError("secure Core connection is not authenticated")
        return [channel.seal_message(message) for message in messages]

    def close(self) -> None:
        if self._core_session_id is not None:
            self.core.close(self._core_session_id)
        if self._channel is not None:
            self._channel.close()
        self._channel = None
        self._core_session_id = None
        self._device_id = None
        self._device_public_key = None
        self._protocol_errors = 0
        self._last_message_type = None
