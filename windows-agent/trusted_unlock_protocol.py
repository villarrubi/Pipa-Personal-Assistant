"""Cryptographic core for the future Pipa Trusted Unlock flow.

This module deliberately does not expose an HTTP endpoint, touch Winlogon, or
create Windows credential serializations.  It only models one-time challenges
and verifies Ed25519 signatures from previously registered devices.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


PROTOCOL_VERSION = 1
AUDIENCE = "pipa-trusted-unlock"
UNLOCK_OPERATION = "unlock"
DEFAULT_TTL_SECONDS = 30
MAX_TTL_SECONDS = 60
DEFAULT_CLOCK_SKEW_SECONDS = 5
NONCE_BYTES = 32

_IDENTIFIER_PATTERN = re.compile(r"^[^\x00-\x1f]{1,128}$")
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


class TrustedUnlockError(Exception):
    """Base class for expected protocol validation failures."""


class UnknownDeviceError(TrustedUnlockError):
    """The device is not paired or has been revoked."""


class UnknownChallengeError(TrustedUnlockError):
    """The challenge was not issued by this verifier or has expired."""


class ChallengeMismatchError(TrustedUnlockError):
    """The response is bound to a different device than the challenge."""


class ExpiredChallengeError(TrustedUnlockError):
    """The challenge is outside its permitted time window."""


class InvalidResponseError(TrustedUnlockError):
    """The response signature or its encoding is invalid."""


class ReplayDetectedError(TrustedUnlockError):
    """A previously accepted challenge response was presented again."""


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a non-empty printable string")
    return value


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64url(value: str) -> bytes:
    if not isinstance(value, str) or _BASE64URL_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid base64url value")

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _now_seconds(now: int | float | None) -> int:
    return int(time.time() if now is None else now)


@dataclass(frozen=True)
class Challenge:
    """A short-lived request issued by the verifier to one device."""

    challenge_id: str
    device_id: str
    nonce: str
    issued_at: int
    expires_at: int
    operation: str = UNLOCK_OPERATION
    audience: str = AUDIENCE
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _validate_identifier(self.challenge_id, "challenge_id")
        _validate_identifier(self.device_id, "device_id")
        _validate_identifier(self.operation, "operation")
        _validate_identifier(self.audience, "audience")

        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError("unsupported protocol version")
        if not isinstance(self.issued_at, int) or not isinstance(self.expires_at, int):
            raise ValueError("challenge timestamps must be integers")
        if self.expires_at <= self.issued_at:
            raise ValueError("challenge must expire after it is issued")

        try:
            nonce = _decode_base64url(self.nonce)
        except ValueError as error:
            raise ValueError("nonce must be valid base64url") from error

        if len(nonce) != NONCE_BYTES:
            raise ValueError(f"nonce must contain {NONCE_BYTES} bytes")

    def as_dict(self) -> dict[str, object]:
        return {
            "audience": self.audience,
            "challenge_id": self.challenge_id,
            "device_id": self.device_id,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "nonce": self.nonce,
            "operation": self.operation,
            "protocol_version": self.protocol_version,
        }

    def signing_bytes(self) -> bytes:
        """Return the canonical bytes both sides must sign and verify."""
        return json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


@dataclass(frozen=True)
class SignedChallenge:
    """A device response containing only the challenge binding and signature."""

    challenge_id: str
    device_id: str
    signature: str

    def __post_init__(self) -> None:
        _validate_identifier(self.challenge_id, "challenge_id")
        _validate_identifier(self.device_id, "device_id")
        try:
            signature = _decode_base64url(self.signature)
        except ValueError as error:
            raise ValueError("signature must be valid base64url") from error
        if len(signature) != 64:
            raise ValueError("Ed25519 signatures must contain 64 bytes")

    def signature_bytes(self) -> bytes:
        return _decode_base64url(self.signature)


@dataclass(frozen=True)
class VerifiedAuthorization:
    """Proof that one challenge was accepted by the verifier."""

    challenge_id: str
    device_id: str
    operation: str
    verified_at: int
    expires_at: int


def public_key_to_base64(public_key: Ed25519PublicKey) -> str:
    """Encode a public key for pairing metadata; never use this for a private key."""
    if not isinstance(public_key, Ed25519PublicKey):
        raise TypeError("public_key must be an Ed25519PublicKey")

    raw_key = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _encode_base64url(raw_key)


def public_key_from_base64(value: str) -> Ed25519PublicKey:
    raw_key = _decode_base64url(value)
    if len(raw_key) != 32:
        raise ValueError("Ed25519 public keys must contain 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw_key)


def create_signed_response(
    challenge: Challenge,
    private_key: Ed25519PrivateKey,
) -> SignedChallenge:
    """Sign a challenge on the authorized device side."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private_key must be an Ed25519PrivateKey")

    signature = private_key.sign(challenge.signing_bytes())
    return SignedChallenge(
        challenge_id=challenge.challenge_id,
        device_id=challenge.device_id,
        signature=_encode_base64url(signature),
    )


class AuthorizationVerifier:
    """Issue and verify one-time challenges for paired devices.

    The verifier keeps pending and consumed challenge IDs in memory.  This is
    intentionally fail-closed across process restarts: old challenges are not
    accepted after a restart.  Durable pairing/revocation storage belongs to a
    later phase and must be protected separately.
    """

    def __init__(
        self,
        trusted_devices: Mapping[str, Ed25519PublicKey] | None = None,
        *,
        clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
    ) -> None:
        if clock_skew_seconds < 0:
            raise ValueError("clock_skew_seconds cannot be negative")

        self._trusted_devices: dict[str, Ed25519PublicKey] = {}
        self._pending: dict[str, Challenge] = {}
        self._consumed: dict[str, int] = {}
        self._clock_skew_seconds = clock_skew_seconds
        self._lock = threading.RLock()

        for device_id, public_key in (trusted_devices or {}).items():
            self.register_device(device_id, public_key)

    def register_device(self, device_id: str, public_key: Ed25519PublicKey) -> None:
        _validate_identifier(device_id, "device_id")
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("public_key must be an Ed25519PublicKey")

        with self._lock:
            self._trusted_devices[device_id] = public_key

    def revoke_device(self, device_id: str) -> None:
        with self._lock:
            self._trusted_devices.pop(device_id, None)

    def create_challenge(
        self,
        device_id: str,
        *,
        now: int | float | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> Challenge:
        _validate_identifier(device_id, "device_id")
        if ttl_seconds < 1 or ttl_seconds > MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")

        issued_at = _now_seconds(now)
        challenge = Challenge(
            challenge_id=_encode_base64url(secrets.token_bytes(16)),
            device_id=device_id,
            nonce=_encode_base64url(secrets.token_bytes(NONCE_BYTES)),
            issued_at=issued_at,
            expires_at=issued_at + ttl_seconds,
        )

        with self._lock:
            self._prune(issued_at)
            if device_id not in self._trusted_devices:
                raise UnknownDeviceError(f"device is not trusted: {device_id}")
            self._pending[challenge.challenge_id] = challenge

        return challenge

    def verify_response(
        self,
        response: SignedChallenge,
        *,
        now: int | float | None = None,
    ) -> VerifiedAuthorization:
        if not isinstance(response, SignedChallenge):
            raise TypeError("response must be a SignedChallenge")

        verified_at = _now_seconds(now)

        with self._lock:
            if response.challenge_id in self._consumed:
                raise ReplayDetectedError("challenge response was already consumed")

            challenge = self._pending.get(response.challenge_id)
            if challenge is not None and verified_at > challenge.expires_at:
                del self._pending[challenge.challenge_id]
                self._prune(verified_at)
                raise ExpiredChallengeError("challenge has expired")

            self._prune(verified_at)

            # The challenge may have been removed by pruning if it expired
            # before the explicit check above. It is therefore intentionally
            # reported as unknown after cleanup.
            if challenge is None:
                raise UnknownChallengeError("challenge was not issued by this verifier")

            if response.device_id != challenge.device_id:
                raise ChallengeMismatchError("response device does not match challenge")

            if verified_at < challenge.issued_at - self._clock_skew_seconds:
                raise ExpiredChallengeError("verifier clock is before challenge issuance")
            public_key = self._trusted_devices.get(challenge.device_id)
            if public_key is None:
                raise UnknownDeviceError("device has been revoked")

            try:
                public_key.verify(response.signature_bytes(), challenge.signing_bytes())
            except (InvalidSignature, ValueError) as error:
                raise InvalidResponseError("signature verification failed") from error

            del self._pending[challenge.challenge_id]
            self._consumed[challenge.challenge_id] = challenge.expires_at

            return VerifiedAuthorization(
                challenge_id=challenge.challenge_id,
                device_id=challenge.device_id,
                operation=challenge.operation,
                verified_at=verified_at,
                expires_at=challenge.expires_at,
            )

    def _prune(self, now: int) -> None:
        expired_pending = [
            challenge_id
            for challenge_id, challenge in self._pending.items()
            if challenge.expires_at < now
        ]
        for challenge_id in expired_pending:
            del self._pending[challenge_id]

        expired_consumed = [
            challenge_id
            for challenge_id, expires_at in self._consumed.items()
            if expires_at < now
        ]
        for challenge_id in expired_consumed:
            del self._consumed[challenge_id]

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
