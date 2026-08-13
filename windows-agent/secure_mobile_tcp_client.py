"""Async reference client for the opt-in secure mobile TCP transport.

This is a protocol test client, not an iPhone application.  It keeps the
identity in memory and requires the caller to provide the server public key
and an explicit address.  Its purpose is to exercise the same framing and
handshake that a future iOS client will implement with CryptoKit.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from secure_json_channel import SecureJsonChannel
from secure_session import (
    HandshakeError,
    SecureIdentity,
    SecureSessionError,
    ServerHello,
    complete_client_handshake,
    create_client_hello,
)
from secure_tcp_gateway import (
    MAX_FRAME_BYTES,
    _read_frame,
    _write_frame,
    validate_mobile_bind_host,
    validate_mobile_port,
)


class SecureMobileTcpClientError(SecureSessionError):
    """The network reference client cannot safely continue."""


class SecureMobileTcpClient:
    """Use the v2 Core contract over a newline-delimited TCP stream."""

    def __init__(
        self,
        identity: SecureIdentity,
        server_public_key: Ed25519PublicKey,
        *,
        server_id: str,
        firmware_version: str = "pipa-mobile-tcp-reference",
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
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._channel: SecureJsonChannel | None = None

    @property
    def connected(self) -> bool:
        return self._reader is not None and self._writer is not None and self._channel is not None

    async def connect(self, host: str, port: int) -> list[dict[str, object]]:
        """Connect, authenticate, and announce the confirmation UI."""

        if self.connected:
            raise SecureMobileTcpClientError("mobile TCP client is already connected")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host must be non-empty text")
        host = validate_mobile_bind_host(host.strip())
        validate_mobile_port(port)
        reader, writer = await asyncio.open_connection(host, port, limit=MAX_FRAME_BYTES + 1)
        self._reader = reader
        self._writer = writer
        client_hello, client_ephemeral = create_client_hello(self.identity)
        try:
            await _write_frame(writer, client_hello.as_dict())
            server_payload = await self._receive_frame()
            if server_payload is None:
                raise SecureMobileTcpClientError("server closed during secure handshake")
            client_session = complete_client_handshake(
                self.identity,
                client_hello,
                client_ephemeral,
                ServerHello(**server_payload),
                self.server_public_key,
                expected_server_id=self.server_id,
            )
            self._channel = SecureJsonChannel(client_session)
            responses = await self._send(
                "device_hello",
                firmware_version=self.firmware_version,
                capabilities=list(self.capabilities),
            )
            if len(responses) != 1 or responses[0].get("type") != "device_hello_ack":
                raise SecureMobileTcpClientError("server did not accept the mobile capability announcement")
            return responses
        except (HandshakeError, SecureSessionError, TypeError, ValueError):
            await self.close()
            raise

    async def send_text(self, text: str) -> list[dict[str, object]]:
        return await self._send("text_input", text=text, source="mobile")

    async def request_catalog(self) -> list[dict[str, object]]:
        return (await self.request_catalog_details())["commands"]  # type: ignore[return-value]

    async def request_catalog_details(self) -> dict[str, object]:
        """Request commands and the bounded public integration matrix."""

        responses = await self._send("catalog_request")
        if len(responses) != 1 or responses[0].get("type") != "catalog":
            raise SecureMobileTcpClientError("server did not return a command catalog")
        commands = responses[0].get("commands")
        capabilities = responses[0].get("capabilities", {})
        if not isinstance(commands, list) or not isinstance(capabilities, dict):
            raise SecureMobileTcpClientError("server returned an invalid command catalog")
        return {"commands": commands, "capabilities": capabilities}

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        call_id: str | None = None,
    ) -> list[dict[str, object]]:
        payload: dict[str, object] = {
            "name": name,
            "arguments": dict(arguments or {}),
        }
        if call_id is not None:
            payload["call_id"] = call_id
        return await self._send("tool_call", **payload)

    async def confirm(self, confirmation_id: str, accepted: bool) -> list[dict[str, object]]:
        return await self._send("confirm", confirmation_id=confirmation_id, accepted=accepted)

    async def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
        writer = self._writer
        self._reader = None
        self._writer = None
        self._channel = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _receive_frame(self) -> dict[str, object] | None:
        reader = self._reader
        if reader is None:
            raise SecureMobileTcpClientError("mobile TCP client is not connected")
        try:
            return await _read_frame(reader, timeout=20)
        except SecureSessionError:
            await self.close()
            raise

    async def _send(self, message_type: str, **fields: Any) -> list[dict[str, object]]:
        writer = self._writer
        channel = self._channel
        if writer is None or channel is None:
            raise SecureMobileTcpClientError("mobile TCP client is not connected")
        payload = {"protocol_version": 1, "type": message_type, **fields}
        try:
            await _write_frame(writer, channel.seal_message(payload))
            first = await self._receive_encrypted_frame()
            if first is None:
                raise SecureMobileTcpClientError("server closed the secure session")
            responses = [first]
            if message_type in {
                "text_input",
                "tool_call",
                "confirm",
                "wake",
                "hold_start",
                "hold_end",
                "audio_end",
                "abort",
            }:
                follow_up = await self._receive_encrypted_frame()
                if follow_up is None or follow_up.get("type") != "ui_state":
                    raise SecureMobileTcpClientError("server response batch is incomplete")
                responses.append(follow_up)
            return responses
        except (SecureSessionError, ConnectionError, OSError):
            await self.close()
            raise

    async def _receive_encrypted_frame(self) -> dict[str, object] | None:
        frame = await self._receive_frame()
        if frame is None:
            return None
        channel = self._channel
        if channel is None:
            raise SecureMobileTcpClientError("secure channel is not established")
        try:
            return channel.open_message(frame)
        except SecureSessionError:
            await self.close()
            raise
