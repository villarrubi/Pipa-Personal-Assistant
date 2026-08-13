"""Opt-in encrypted session primitives for the Pipa protocol v2.

Protocol v1 deliberately remains unchanged: it authenticates the device but
does not encrypt its JSON lines.  The running v1 agent does not import this
module.  The opt-in secure serial gateway uses it, and the same reviewed
building block can be reused by a future mobile transport once both ends have
implementations and the upgrade negotiation is tested on real hardware.

The handshake uses:

* Ed25519 signatures for both endpoint identities;
* an ephemeral X25519 exchange for forward secrecy;
* HKDF-SHA256 for directional keys and nonce prefixes; and
* ChaCha20-Poly1305 for ordered, replay-protected records.

No private key or session key is serialised by this module. Callers are
responsible for keeping the identity private key in the platform keystore or
the device's protected storage. The repository's mobile client is only an
in-memory reference used by tests; it is not an iPhone app or network server.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from typing import Literal

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SECURE_PROTOCOL_VERSION = 2
SESSION_ID_BYTES = 16
EPHEMERAL_KEY_BYTES = 32
NONCE_BYTES = 32
AEAD_KEY_BYTES = 32
NONCE_PREFIX_BYTES = 4
MAX_SESSION_ID_LENGTH = 128
MAX_RECORD_BYTES = 64 * 1024
MAX_ADDITIONAL_DATA_BYTES = 1024
MAX_SEQUENCE = (1 << 64) - 1
_BASE64URL_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_IDENTITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_HKDF_INFO = b"pipa/secure-session/v2"


class SecureSessionError(ValueError):
    """Base class for expected secure-session failures."""


class HandshakeError(SecureSessionError):
    """The key exchange or its identity binding is invalid."""


class RecordError(SecureSessionError):
    """An encrypted record is malformed or cannot be authenticated."""


class ReplayError(RecordError):
    """A record did not have the next expected sequence number."""


class ClosedSessionError(RecordError):
    """The caller attempted to use a closed session."""


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: object, *, name: str, expected_length: int | None = None) -> bytes:
    if not isinstance(value, str) or not value or any(char not in _BASE64URL_ALPHABET for char in value):
        raise HandshakeError(f"{name} must be unpadded base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise HandshakeError(f"{name} is not valid base64url") from error
    if _encode(decoded) != value:
        raise HandshakeError(f"{name} is not canonical base64url")
    if expected_length is not None and len(decoded) != expected_length:
        raise HandshakeError(f"{name} must contain {expected_length} bytes")
    return decoded


def _session_id(value: str) -> str:
    if not isinstance(value, str) or _SESSION_ID_PATTERN.fullmatch(value) is None:
        raise HandshakeError("session_id has an invalid length")
    return value


def _identity_id(value: str) -> str:
    if not isinstance(value, str) or _IDENTITY_ID_PATTERN.fullmatch(value) is None:
        raise HandshakeError("identity_id has an invalid length")
    return value


def _canonical(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise HandshakeError("handshake data is not canonical JSON") from error


def _public_bytes(key: X25519PublicKey | Ed25519PublicKey) -> bytes:
    return key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)


@dataclass(frozen=True)
class SecureIdentity:
    """An Ed25519 identity used only for authenticated handshake signatures."""

    identity_id: str
    private_key: Ed25519PrivateKey

    def __post_init__(self) -> None:
        _identity_id(self.identity_id)
        if not isinstance(self.private_key, Ed25519PrivateKey):
            raise TypeError("private_key must be an Ed25519PrivateKey")

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self.private_key.public_key()

    @property
    def public_key_b64(self) -> str:
        return _encode(_public_bytes(self.public_key))


@dataclass(frozen=True)
class ClientHello:
    """First key-exchange message sent by the device/client."""

    session_id: str
    client_id: str
    client_ephemeral_public_key: str
    client_nonce: str
    signature: str
    protocol_version: int = SECURE_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _validate_handshake_fields(
            self.protocol_version,
            self.session_id,
            self.client_id,
            self.client_ephemeral_public_key,
            self.client_nonce,
        )
        _decode(self.signature, name="signature", expected_length=64)

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "client_ephemeral_public_key": self.client_ephemeral_public_key,
            "client_id": self.client_id,
            "client_nonce": self.client_nonce,
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
        }

    def as_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "signature": self.signature}


@dataclass(frozen=True)
class ServerHello:
    """Server response binding both ephemeral keys to the two identities."""

    session_id: str
    client_id: str
    server_id: str
    client_ephemeral_public_key: str
    client_nonce: str
    server_ephemeral_public_key: str
    server_nonce: str
    signature: str
    protocol_version: int = SECURE_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _validate_handshake_fields(
            self.protocol_version,
            self.session_id,
            self.client_id,
            self.client_ephemeral_public_key,
            self.client_nonce,
        )
        _identity_id(self.server_id)
        _decode(self.server_ephemeral_public_key, name="server_ephemeral_public_key", expected_length=32)
        _decode(self.server_nonce, name="server_nonce", expected_length=32)
        _decode(self.signature, name="signature", expected_length=64)

    def transcript_dict(self) -> dict[str, object]:
        return {
            "client_ephemeral_public_key": self.client_ephemeral_public_key,
            "client_id": self.client_id,
            "client_nonce": self.client_nonce,
            "protocol_version": self.protocol_version,
            "server_ephemeral_public_key": self.server_ephemeral_public_key,
            "server_id": self.server_id,
            "server_nonce": self.server_nonce,
            "session_id": self.session_id,
        }

    def as_dict(self) -> dict[str, object]:
        return {**self.transcript_dict(), "signature": self.signature}


def _validate_handshake_fields(
    protocol_version: int,
    session_id: str,
    client_id: str,
    client_ephemeral_public_key: str,
    client_nonce: str,
) -> None:
    if protocol_version != SECURE_PROTOCOL_VERSION:
        raise HandshakeError("unsupported secure protocol version")
    _session_id(session_id)
    _identity_id(client_id)
    _decode(client_ephemeral_public_key, name="client_ephemeral_public_key", expected_length=32)
    _decode(client_nonce, name="client_nonce", expected_length=32)


def _client_signature_data(hello: ClientHello) -> bytes:
    return _canonical({"role": "client", **hello.unsigned_dict()})


def _server_signature_data(hello: ServerHello) -> bytes:
    return _canonical({"role": "server", **hello.transcript_dict()})


def _transcript_hash(hello: ServerHello) -> bytes:
    return hashlib.sha256(_canonical(hello.transcript_dict())).digest()


def create_client_hello(
    identity: SecureIdentity,
    *,
    session_id: str | None = None,
    ephemeral_private_key: X25519PrivateKey | None = None,
    nonce: bytes | None = None,
) -> tuple[ClientHello, X25519PrivateKey]:
    """Create a client hello and return its ephemeral private key in memory."""

    if not isinstance(identity, SecureIdentity):
        raise TypeError("identity must be SecureIdentity")
    private_key = ephemeral_private_key or X25519PrivateKey.generate()
    if not isinstance(private_key, X25519PrivateKey):
        raise TypeError("ephemeral_private_key must be an X25519PrivateKey")
    client_nonce = secrets.token_bytes(NONCE_BYTES) if nonce is None else nonce
    if not isinstance(client_nonce, bytes) or len(client_nonce) != NONCE_BYTES:
        raise HandshakeError(f"nonce must contain {NONCE_BYTES} bytes")
    unsigned = ClientHello(
        session_id=_session_id(session_id or _encode(secrets.token_bytes(SESSION_ID_BYTES))),
        client_id=identity.identity_id,
        client_ephemeral_public_key=_encode(_public_bytes(private_key.public_key())),
        client_nonce=_encode(client_nonce),
        signature="A" * 86,
    ).unsigned_dict()
    signature = _encode(identity.private_key.sign(_canonical({"role": "client", **unsigned})))
    return ClientHello(**unsigned, signature=signature), private_key


def create_server_hello(
    identity: SecureIdentity,
    client_hello: ClientHello,
    client_public_key: Ed25519PublicKey,
    *,
    ephemeral_private_key: X25519PrivateKey | None = None,
    nonce: bytes | None = None,
) -> tuple[ServerHello, SecureSession]:
    """Verify the client and create the authenticated server response."""

    if not isinstance(identity, SecureIdentity):
        raise TypeError("identity must be SecureIdentity")
    if not isinstance(client_hello, ClientHello):
        raise TypeError("client_hello must be ClientHello")
    if not isinstance(client_public_key, Ed25519PublicKey):
        raise TypeError("client_public_key must be an Ed25519PublicKey")
    try:
        client_public_key.verify(
            _decode(client_hello.signature, name="signature", expected_length=64),
            _client_signature_data(client_hello),
        )
    except (InvalidSignature, HandshakeError) as error:
        raise HandshakeError("client identity signature is invalid") from error

    private_key = ephemeral_private_key or X25519PrivateKey.generate()
    if not isinstance(private_key, X25519PrivateKey):
        raise TypeError("ephemeral_private_key must be an X25519PrivateKey")
    server_nonce = secrets.token_bytes(NONCE_BYTES) if nonce is None else nonce
    if not isinstance(server_nonce, bytes) or len(server_nonce) != NONCE_BYTES:
        raise HandshakeError(f"nonce must contain {NONCE_BYTES} bytes")
    hello_without_signature = {
        **client_hello.unsigned_dict(),
        "server_ephemeral_public_key": _encode(_public_bytes(private_key.public_key())),
        "server_id": identity.identity_id,
        "server_nonce": _encode(server_nonce),
    }
    server_hello = ServerHello(
        **hello_without_signature,
        signature=_encode(
            identity.private_key.sign(_canonical({"role": "server", **hello_without_signature}))
        ),
    )
    session = _derive_session(
        role="server",
        session_id=server_hello.session_id,
        client_ephemeral_public_key=client_hello.client_ephemeral_public_key,
        own_ephemeral_private_key=private_key,
        server_ephemeral_public_key=server_hello.server_ephemeral_public_key,
        transcript_hash=_transcript_hash(server_hello),
    )
    return server_hello, session


def complete_client_handshake(
    identity: SecureIdentity,
    client_hello: ClientHello,
    client_ephemeral_private_key: X25519PrivateKey,
    server_hello: ServerHello,
    server_public_key: Ed25519PublicKey,
    *,
    expected_server_id: str | None = None,
) -> SecureSession:
    """Verify the server response and derive the client-side session keys."""

    if not isinstance(identity, SecureIdentity):
        raise TypeError("identity must be SecureIdentity")
    if client_hello.client_id != identity.identity_id:
        raise HandshakeError("client hello identity does not match")
    if not isinstance(client_ephemeral_private_key, X25519PrivateKey):
        raise TypeError("client_ephemeral_private_key must be an X25519PrivateKey")
    if not isinstance(server_hello, ServerHello) or not isinstance(server_public_key, Ed25519PublicKey):
        raise TypeError("server hello and public key have invalid types")
    if expected_server_id is not None:
        _identity_id(expected_server_id)
        if server_hello.server_id != expected_server_id:
            raise HandshakeError("server identity id does not match the pinned identity")
    if server_hello.session_id != client_hello.session_id or server_hello.client_id != client_hello.client_id:
        raise HandshakeError("server response is not bound to the client hello")
    if (
        server_hello.client_ephemeral_public_key != client_hello.client_ephemeral_public_key
        or server_hello.client_nonce != client_hello.client_nonce
    ):
        raise HandshakeError("server response changed the client transcript")
    expected_client_key = _encode(_public_bytes(client_ephemeral_private_key.public_key()))
    if expected_client_key != client_hello.client_ephemeral_public_key:
        raise HandshakeError("client ephemeral key does not match the hello")
    try:
        server_public_key.verify(
            _decode(server_hello.signature, name="signature", expected_length=64),
            _server_signature_data(server_hello),
        )
    except (InvalidSignature, HandshakeError) as error:
        raise HandshakeError("server identity signature is invalid") from error

    return _derive_session(
        role="client",
        session_id=server_hello.session_id,
        client_ephemeral_public_key=client_hello.client_ephemeral_public_key,
        own_ephemeral_private_key=client_ephemeral_private_key,
        server_ephemeral_public_key=server_hello.server_ephemeral_public_key,
        transcript_hash=_transcript_hash(server_hello),
    )


def secure_session_from_shared_secret(
    session_id: str,
    shared_secret: bytes,
    transcript_hash: bytes,
    *,
    role: Literal["client", "server"],
) -> SecureSession:
    """Build a record layer from a completed X25519 exchange.

    This low-level entry point is useful for deterministic Python↔firmware
    vectors. Production callers should use the authenticated handshake helpers
    above so that the shared secret is never accepted without identity binding.
    """

    _session_id(session_id)
    if role not in {"client", "server"}:
        raise ValueError("role must be client or server")
    if not isinstance(shared_secret, bytes) or len(shared_secret) != 32:
        raise HandshakeError("shared_secret must contain 32 bytes")
    if not isinstance(transcript_hash, bytes) or len(transcript_hash) != 32:
        raise HandshakeError("transcript_hash must contain 32 bytes")
    if not any(shared_secret):
        raise HandshakeError("shared_secret must not be all zeroes")

    material = HKDF(
        algorithm=hashes.SHA256(),
        length=(AEAD_KEY_BYTES * 2) + (NONCE_PREFIX_BYTES * 2),
        salt=transcript_hash,
        info=_HKDF_INFO + transcript_hash,
    ).derive(shared_secret)
    client_key = material[:AEAD_KEY_BYTES]
    server_key = material[AEAD_KEY_BYTES : AEAD_KEY_BYTES * 2]
    client_prefix = material[AEAD_KEY_BYTES * 2 : AEAD_KEY_BYTES * 2 + NONCE_PREFIX_BYTES]
    server_prefix = material[AEAD_KEY_BYTES * 2 + NONCE_PREFIX_BYTES :]
    if role == "client":
        return SecureSession(session_id, client_key, server_key, client_prefix, server_prefix)
    return SecureSession(session_id, server_key, client_key, server_prefix, client_prefix)


def _derive_session(
    *,
    role: Literal["client", "server"],
    session_id: str,
    client_ephemeral_public_key: str,
    own_ephemeral_private_key: X25519PrivateKey,
    server_ephemeral_public_key: str,
    transcript_hash: bytes,
) -> SecureSession:
    try:
        if role == "client":
            shared_secret = own_ephemeral_private_key.exchange(
                X25519PublicKey.from_public_bytes(
                    _decode(
                        server_ephemeral_public_key, name="server_ephemeral_public_key", expected_length=32
                    )
                )
            )
        else:
            shared_secret = own_ephemeral_private_key.exchange(
                X25519PublicKey.from_public_bytes(
                    _decode(
                        client_ephemeral_public_key, name="client_ephemeral_public_key", expected_length=32
                    )
                )
            )
    except (ValueError, HandshakeError) as error:
        raise HandshakeError("ephemeral key exchange failed") from error
    if not any(shared_secret):
        raise HandshakeError("ephemeral key exchange produced a weak shared secret")

    return secure_session_from_shared_secret(
        session_id,
        shared_secret,
        transcript_hash,
        role=role,
    )


class SecureSession:
    """Directional ChaCha20-Poly1305 record layer with strict ordering."""

    def __init__(
        self,
        session_id: str,
        send_key: bytes,
        receive_key: bytes,
        send_nonce_prefix: bytes,
        receive_nonce_prefix: bytes,
    ) -> None:
        _session_id(session_id)
        if any(
            not isinstance(value, bytes) or len(value) != expected
            for value, expected in (
                (send_key, AEAD_KEY_BYTES),
                (receive_key, AEAD_KEY_BYTES),
                (send_nonce_prefix, NONCE_PREFIX_BYTES),
                (receive_nonce_prefix, NONCE_PREFIX_BYTES),
            )
        ):
            raise TypeError("session key material has an invalid length")
        self.session_id = session_id
        self._send_cipher = ChaCha20Poly1305(send_key)
        self._receive_cipher = ChaCha20Poly1305(receive_key)
        self._send_nonce_prefix = send_nonce_prefix
        self._receive_nonce_prefix = receive_nonce_prefix
        self._send_sequence = 0
        self._receive_sequence = 0
        self._closed = False

    def seal(self, payload: bytes, *, additional_data: bytes = b"") -> dict[str, object]:
        self._ensure_open()
        if not isinstance(payload, bytes) or len(payload) > MAX_RECORD_BYTES:
            raise RecordError(f"payload must be bytes of at most {MAX_RECORD_BYTES} bytes")
        additional_data = self._validate_additional_data(additional_data)
        sequence = self._send_sequence
        if sequence > MAX_SEQUENCE:
            raise RecordError("send sequence exhausted")
        header = {
            "protocol_version": SECURE_PROTOCOL_VERSION,
            "sequence": sequence,
            "session_id": self.session_id,
        }
        ciphertext = self._send_cipher.encrypt(
            self._nonce(self._send_nonce_prefix, sequence),
            payload,
            _canonical(header) + additional_data,
        )
        self._send_sequence += 1
        return {**header, "ciphertext": _encode(ciphertext)}

    def open(self, frame: dict[str, object], *, additional_data: bytes = b"") -> bytes:
        self._ensure_open()
        if not isinstance(frame, dict):
            raise RecordError("encrypted frame must be an object")
        if (
            frame.get("protocol_version") != SECURE_PROTOCOL_VERSION
            or frame.get("session_id") != self.session_id
        ):
            raise RecordError("encrypted frame is for another protocol or session")
        sequence = frame.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence <= MAX_SEQUENCE:
            raise RecordError("encrypted frame sequence is invalid")
        if sequence != self._receive_sequence:
            raise ReplayError("encrypted frame is not the next expected sequence")
        ciphertext = _decode_record(frame.get("ciphertext"))
        if len(ciphertext) > MAX_RECORD_BYTES + 16:
            raise RecordError("encrypted frame is too large")
        additional_data = self._validate_additional_data(additional_data)
        header = {
            "protocol_version": SECURE_PROTOCOL_VERSION,
            "sequence": sequence,
            "session_id": self.session_id,
        }
        try:
            payload = self._receive_cipher.decrypt(
                self._nonce(self._receive_nonce_prefix, sequence),
                ciphertext,
                _canonical(header) + additional_data,
            )
        except InvalidTag as error:
            # Do not expose whether the failure was a bad tag, malformed
            # ciphertext, or an implementation detail of the crypto backend.
            raise RecordError("encrypted frame authentication failed") from error
        if len(payload) > MAX_RECORD_BYTES:
            raise RecordError("decrypted payload is too large")
        self._receive_sequence += 1
        return payload

    def close(self) -> None:
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedSessionError("secure session is closed")

    @staticmethod
    def _nonce(prefix: bytes, sequence: int) -> bytes:
        return prefix + sequence.to_bytes(8, "big")

    @staticmethod
    def _validate_additional_data(value: bytes) -> bytes:
        if not isinstance(value, bytes) or len(value) > MAX_ADDITIONAL_DATA_BYTES:
            raise RecordError(f"additional_data must be bytes of at most {MAX_ADDITIONAL_DATA_BYTES} bytes")
        return value


def _decode_record(value: object) -> bytes:
    try:
        return _decode(value, name="ciphertext")
    except HandshakeError as error:
        raise RecordError(str(error)) from error
