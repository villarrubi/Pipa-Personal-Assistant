"""Reference mobile client for the encrypted Pipa v2 contract.

This module is deliberately transport-neutral and keeps every key in memory.
It is used by tests and diagnostics to represent an iPhone-like client before
an actual iOS app and network transport exist. It never opens a socket and it
does not persist a private key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from secure_core_connection import SecureCoreConnection
from secure_json_channel import SecureJsonChannel
from secure_session import (
    HandshakeError,
    SecureIdentity,
    SecureSessionError,
    ServerHello,
    complete_client_handshake,
    create_client_hello,
)


class SecureMobileClientError(SecureSessionError):
    """The reference client cannot safely continue its secure session."""


class SecureMobileClient:
    """In-memory client model for a future mobile application.

    The caller supplies a pinned server public key out of band. The client
    announces ``display`` and ``touch`` only because this reference represents
    a mobile UI capable of showing and accepting a confirmation; an audio
    transport is intentionally not implied.
    """

    def __init__(
        self,
        identity: SecureIdentity,
        server_public_key: Ed25519PublicKey,
        *,
        server_id: str,
        firmware_version: str = "pipa-mobile-reference",
        capabilities: tuple[str, ...] = ("display", "touch", "mobile", "text_input"),
    ) -> None:
        if not isinstance(identity, SecureIdentity):
            raise TypeError("identity must be SecureIdentity")
        if not isinstance(server_public_key, Ed25519PublicKey):
            raise TypeError("server_public_key must be Ed25519PublicKey")
        if not isinstance(server_id, str) or not server_id.strip():
            raise ValueError("server_id must be non-empty text")
        if not isinstance(firmware_version, str) or not firmware_version.strip():
            raise ValueError("firmware_version must be non-empty text")
        if not isinstance(capabilities, tuple) or not capabilities:
            raise ValueError("capabilities must be a non-empty tuple")
        self.identity = identity
        self.server_public_key = server_public_key
        self.server_id = server_id.strip()
        self.firmware_version = firmware_version.strip()
        self.capabilities = capabilities
        self._connection: SecureCoreConnection | None = None
        self._channel: SecureJsonChannel | None = None

    @property
    def connected(self) -> bool:
        return self._connection is not None and self._channel is not None

    def connect(self, connection: SecureCoreConnection) -> list[dict[str, object]]:
        """Complete v2 and announce the mobile confirmation surface."""

        if self.connected:
            raise SecureMobileClientError("mobile client is already connected")
        if not isinstance(connection, SecureCoreConnection):
            raise TypeError("connection must be SecureCoreConnection")

        client_hello, client_ephemeral = create_client_hello(self.identity)
        try:
            server_payload = connection.accept_client_hello(client_hello.as_dict())
            client_session = complete_client_handshake(
                self.identity,
                client_hello,
                client_ephemeral,
                ServerHello(**server_payload),
                self.server_public_key,
                expected_server_id=self.server_id,
            )
        except (HandshakeError, SecureSessionError, TypeError, ValueError):
            connection.close()
            raise

        self._connection = connection
        self._channel = SecureJsonChannel(client_session)
        responses = self._send(
            "device_hello",
            firmware_version=self.firmware_version,
            capabilities=list(self.capabilities),
        )
        if len(responses) != 1 or responses[0].get("type") != "device_hello_ack":
            self.close()
            raise SecureMobileClientError("server did not accept the mobile capability announcement")
        return responses

    def send_text(self, text: str) -> list[dict[str, object]]:
        """Send text as a mobile-originated command through the Core parser."""

        return self._send("text_input", text=text, source="mobile")

    def request_catalog(self) -> list[dict[str, object]]:
        """Request the bounded, non-sensitive command catalog from the Core."""

        return self.request_catalog_details()["commands"]  # type: ignore[return-value]

    def request_catalog_details(self) -> dict[str, object]:
        """Request commands and the bounded public integration matrix."""

        responses = self._send("catalog_request")
        if len(responses) != 1 or responses[0].get("type") != "catalog":
            raise SecureMobileClientError("server did not return a command catalog")
        commands = responses[0].get("commands")
        capabilities = responses[0].get("capabilities", {})
        if not isinstance(commands, list) or not isinstance(capabilities, dict):
            raise SecureMobileClientError("server returned an invalid command catalog")
        return {"commands": commands, "capabilities": capabilities}

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        call_id: str | None = None,
    ) -> list[dict[str, object]]:
        payload: dict[str, object] = {
            "name": name,
            "arguments": dict(arguments or {}),
        }
        if call_id is not None:
            payload["call_id"] = call_id
        return self._send("tool_call", **payload)

    def confirm(self, confirmation_id: str, accepted: bool) -> list[dict[str, object]]:
        return self._send(
            "confirm",
            confirmation_id=confirmation_id,
            accepted=accepted,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None
        self._channel = None

    def _send(self, message_type: str, **fields: Any) -> list[dict[str, object]]:
        connection = self._connection
        channel = self._channel
        if connection is None or channel is None:
            raise SecureMobileClientError("mobile client is not connected")
        payload = {"protocol_version": 1, "type": message_type, **fields}
        try:
            frames = connection.process_frame(channel.seal_message(payload))
            return [channel.open_message(frame) for frame in frames]
        except SecureSessionError:
            self.close()
            raise
