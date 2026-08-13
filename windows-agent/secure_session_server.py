"""Transport-independent, opt-in server endpoint for secure session v2.

This adapter deliberately does not listen on a socket, persist a private key,
or replace the running v1 WebSocket. It validates the bounded ClientHello
shape, selects the already paired Ed25519 public key, and returns the signed
ServerHello plus an in-memory record layer for a transport adapter.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from secure_session import (
    ClientHello,
    HandshakeError,
    SecureIdentity,
    SecureSession,
    create_server_hello,
)

MAX_CLIENT_HELLO_BYTES = 4096
MAX_USED_SESSION_IDS = 4096
SESSION_ID_REPLAY_TTL_SECONDS = 30 * 60
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


@dataclass(frozen=True)
class SecureSessionServer:
    """Create v2 sessions from paired device identities without opening I/O."""

    identity: SecureIdentity
    trusted_devices: Mapping[str, Ed25519PublicKey]
    _used_session_ids: OrderedDict[str, float] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
        compare=False,
    )
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SecureIdentity):
            raise TypeError("identity must be SecureIdentity")
        copied = self._copy_trusted_devices(self.trusted_devices)
        object.__setattr__(self, "trusted_devices", copied)

    @staticmethod
    def _copy_trusted_devices(
        trusted_devices: Mapping[str, Ed25519PublicKey],
    ) -> dict[str, Ed25519PublicKey]:
        copied = dict(trusted_devices)
        for device_id, public_key in copied.items():
            if not isinstance(device_id, str) or not device_id:
                raise ValueError("trusted device IDs must be non-empty strings")
            if not isinstance(public_key, Ed25519PublicKey):
                raise TypeError("trusted device keys must be Ed25519PublicKey values")
        return copied

    @property
    def public_key_b64(self) -> str:
        """Public server identity for an out-of-band provisioning channel."""

        return self.identity.public_key_b64

    def refresh_trusted_devices(self, trusted_devices: Mapping[str, Ed25519PublicKey]) -> None:
        """Replace paired keys while preserving the replay cache."""

        copied = self._copy_trusted_devices(trusted_devices)
        with self._lock:
            object.__setattr__(self, "trusted_devices", copied)

    def is_trusted_device(self, device_id: str, public_key: Ed25519PublicKey) -> bool:
        """Check whether a connected device still has the same public key."""

        if not isinstance(public_key, Ed25519PublicKey):
            return False
        with self._lock:
            current = self.trusted_devices.get(device_id)
            if current is None:
                return False
            raw_current = current.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            raw_expected = public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            return raw_current == raw_expected

    def trusted_device_public_key(self, device_id: str) -> Ed25519PublicKey | None:
        """Return the current public key for a device under the trust lock."""

        with self._lock:
            return self.trusted_devices.get(device_id)

    def accept_client_hello(self, payload: Mapping[str, Any]) -> tuple[dict[str, object], SecureSession]:
        """Verify a bounded client hello and create a memory-only session."""

        if not isinstance(payload, Mapping):
            raise HandshakeError("secure client hello must be an object")
        try:
            encoded_size = len(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError, RecursionError) as error:
            raise HandshakeError("secure client hello is not valid JSON data") from error
        if encoded_size > MAX_CLIENT_HELLO_BYTES:
            raise HandshakeError("secure client hello is too large")

        unknown_fields = set(payload) - _CLIENT_HELLO_FIELDS
        if unknown_fields or set(payload) != _CLIENT_HELLO_FIELDS:
            raise HandshakeError("secure client hello has an invalid field set")
        try:
            client_hello = ClientHello(**dict(payload))
        except (TypeError, ValueError) as error:
            raise HandshakeError("secure client hello is malformed") from error

        with self._lock:
            client_public_key = self.trusted_devices.get(client_hello.client_id)
            if client_public_key is None:
                raise HandshakeError("client identity is not paired")
            now = time.monotonic()
            cutoff = now - SESSION_ID_REPLAY_TTL_SECONDS
            while self._used_session_ids:
                oldest_id, oldest_seen = next(iter(self._used_session_ids.items()))
                if oldest_seen > cutoff:
                    break
                self._used_session_ids.pop(oldest_id)
            if client_hello.session_id in self._used_session_ids:
                raise HandshakeError("secure client hello was already consumed")
            server_hello, session = create_server_hello(
                self.identity,
                client_hello,
                client_public_key,
            )
            if len(self._used_session_ids) >= MAX_USED_SESSION_IDS:
                self._used_session_ids.popitem(last=False)
            self._used_session_ids[client_hello.session_id] = now
        return server_hello.as_dict(), session
