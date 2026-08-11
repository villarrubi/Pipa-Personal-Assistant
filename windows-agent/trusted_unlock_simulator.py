"""In-memory trusted-device simulator used only by automated tests.

The private key is generated at construction time and is never serialized,
written to disk, or exposed by a command-line interface.  This lets the
protocol be exercised before the physical Waveshare/mobile device exists
without creating a fake persistent credential on the PC.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trusted_unlock_protocol import (
    Challenge,
    SignedChallenge,
    create_signed_response,
    public_key_to_base64,
)


@dataclass
class InMemoryTrustedDevice:
    """Ephemeral device identity for tests; never use for production pairing."""

    device_id: str
    _private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls, device_id: str) -> "InMemoryTrustedDevice":
        return cls(device_id=device_id, _private_key=Ed25519PrivateKey.generate())

    @property
    def public_key_base64(self) -> str:
        return public_key_to_base64(self._private_key.public_key())

    @property
    def public_key(self):
        return self._private_key.public_key()

    def sign(self, challenge: Challenge) -> SignedChallenge:
        if challenge.device_id != self.device_id:
            raise ValueError("challenge is addressed to another device")
        return create_signed_response(challenge, self._private_key)
