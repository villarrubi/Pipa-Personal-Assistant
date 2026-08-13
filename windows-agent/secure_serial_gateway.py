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
import time
from collections.abc import Callable, Mapping
from typing import Any

from pipa_serial_gateway import MAX_LINE_BYTES, SerialGateway
from secure_core_connection import SecureCoreConnection
from secure_identity_store import (
    SecureIdentityStore,
    SecureIdentityStoreError,
    default_secure_identity_path,
)
from secure_session import HandshakeError, SecureIdentity, SecureSessionError
from secure_session_server import SecureSessionServer
from trusted_unlock_devices import WindowsRegistryDeviceStore

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

    def _serve_connection(self, connection) -> None:
        secure_core = SecureCoreConnection(
            self.core,
            self.server_identity,
            self.trusted_devices,
            session_server=self.session_server,
        )
        last_activity = time.monotonic()
        last_trust_check = 0.0
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
                raw = connection.read_until(b"\n", MAX_LINE_BYTES + 1)
                if not raw:
                    continue
                if raw.startswith(b"#"):
                    continue
                if len(raw) > MAX_LINE_BYTES:
                    connection.reset_input_buffer()
                    LOGGER.warning("secure serial message exceeded the configured limit")
                    break
                try:
                    payload = _strict_json(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    LOGGER.warning("secure serial message was not valid JSON")
                    break

                if not secure_core.authenticated:
                    if set(payload) != _CLIENT_HELLO_FIELDS or payload.get("protocol_version") != 2:
                        LOGGER.warning("secure serial connection did not start with ClientHello")
                        break
                    try:
                        server_hello = secure_core.accept_client_hello(payload)
                    except (HandshakeError, SecureSessionError, ValueError):
                        LOGGER.warning("secure serial ClientHello was rejected")
                        break
                    self._send(connection, server_hello)
                    last_activity = time.monotonic()
                    # Force one immediate post-handshake check before the
                    # first encrypted application frame is accepted.
                    last_trust_check = 0.0
                    continue

                try:
                    responses = secure_core.process_frame(payload)
                except SecureSessionError:
                    LOGGER.warning("secure serial encrypted frame was rejected")
                    break
                last_activity = time.monotonic()
                for response in responses:
                    self._send(connection, response)
        except Exception:
            LOGGER.exception("unexpected secure serial gateway error")
        finally:
            secure_core.close()

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


def start_configured_secure_gateway(core: PipaCore) -> SecureSerialGateway | None:
    """Create the explicitly requested v2 gateway, failing closed on setup errors."""

    port = os.environ.get("PIPA_SERIAL_PORT", "").strip()
    if not port:
        return None
    server_id = os.environ.get("PIPA_SECURE_SERVER_ID", DEFAULT_SERVER_ID).strip()
    try:
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
        )
        gateway.start()
        LOGGER.info("Pipa secure serial gateway enabled on %s", gateway.port)
        return gateway
    except (SecureIdentityStoreError, TypeError, ValueError) as error:
        LOGGER.error("Could not configure the secure Pipa serial gateway: %s", error)
        return None
    except Exception:
        LOGGER.exception("Could not configure the secure Pipa serial gateway")
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
