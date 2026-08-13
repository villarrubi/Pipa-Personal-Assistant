"""User-scoped DPAPI storage for the Pipa agent identity.

The v1 agent does not load this store. It is the provisioning and loading
building block for opt-in secure session v2: the private Ed25519 key is
generated locally, protected by the current Windows user with DPAPI, and never
written to Git, logs, JSON responses, or the Waveshare.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from secure_session import SecureIdentity

STORE_VERSION = 1
MAX_STORE_BYTES = 16 * 1024
STORE_FIELDS = frozenset({"identity_id", "protected_private_key", "version"})


class SecureIdentityStoreError(RuntimeError):
    """The protected identity cannot be loaded or safely written."""


def _protect(value: bytes) -> bytes:
    """Protect bytes with the current Windows user's DPAPI profile."""

    try:
        import win32crypt
    except ImportError as error:  # pragma: no cover - depends on Windows pywin32
        raise SecureIdentityStoreError("Windows DPAPI requires pywin32") from error
    try:
        return bytes(win32crypt.CryptProtectData(value, "Pipa agent identity", None, None, None, 0))
    except Exception as error:  # pragma: no cover - platform API failure
        raise SecureIdentityStoreError("Windows DPAPI could not protect the identity") from error


def _unprotect(value: bytes) -> bytes:
    """Unprotect bytes with the current Windows user's DPAPI profile."""

    try:
        import win32crypt
    except ImportError as error:  # pragma: no cover - depends on Windows pywin32
        raise SecureIdentityStoreError("Windows DPAPI requires pywin32") from error
    try:
        return bytes(win32crypt.CryptUnprotectData(value, None, None, None, 0)[1])
    except Exception as error:  # pragma: no cover - platform API failure
        raise SecureIdentityStoreError("Windows DPAPI could not unprotect the identity") from error


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: object) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for character in value
        )
    ):
        raise SecureIdentityStoreError("protected identity encoding is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise SecureIdentityStoreError("protected identity encoding is invalid") from error
    if _encode(decoded) != value:
        raise SecureIdentityStoreError("protected identity encoding is not canonical")
    return decoded


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SecureIdentityStoreError("identity store contains duplicate fields")
        result[key] = value
    return result


class SecureIdentityStore:
    """Load or create one DPAPI-protected Ed25519 identity for the agent."""

    def __init__(
        self,
        path: Path,
        *,
        protect: Callable[[bytes], bytes] = _protect,
        unprotect: Callable[[bytes], bytes] = _unprotect,
    ) -> None:
        self.path = Path(path)
        self._protect = protect
        self._unprotect = unprotect

    def load_or_create(self, identity_id: str) -> SecureIdentity:
        if self.path.exists():
            return self.load(identity_id)

        try:
            private_key = Ed25519PrivateKey.generate()
            identity = SecureIdentity(identity_id, private_key)
        except (TypeError, ValueError) as error:
            raise SecureIdentityStoreError("agent identity ID is invalid") from error
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        protected = self._protect(private_bytes)
        if not isinstance(protected, bytes) or not protected or len(protected) > MAX_STORE_BYTES:
            raise SecureIdentityStoreError("DPAPI returned an invalid protected identity")
        self._write(identity.identity_id, protected)
        return identity

    def load(self, identity_id: str) -> SecureIdentity:
        """Load an existing identity without creating one as a side effect."""

        if not self.path.exists():
            raise SecureIdentityStoreError("the protected agent identity does not exist")
        return self._load(identity_id)

    def _load(self, identity_id: str) -> SecureIdentity:
        try:
            raw = self.path.read_bytes()
        except OSError as error:
            raise SecureIdentityStoreError("could not read the protected agent identity") from error
        if len(raw) > MAX_STORE_BYTES:
            raise SecureIdentityStoreError("protected agent identity is too large")
        try:
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError, SecureIdentityStoreError) as error:
            raise SecureIdentityStoreError("protected agent identity is invalid JSON") from error
        if (
            not isinstance(document, dict)
            or set(document) != STORE_FIELDS
            or document.get("version") != STORE_VERSION
            or document.get("identity_id") != identity_id
        ):
            raise SecureIdentityStoreError("protected agent identity metadata does not match")
        protected = _decode(document.get("protected_private_key"))
        if not 1 <= len(protected) <= MAX_STORE_BYTES:
            raise SecureIdentityStoreError("protected agent identity has an invalid size")
        try:
            private_bytes = self._unprotect(protected)
            if not isinstance(private_bytes, bytes) or len(private_bytes) != 32:
                raise ValueError("invalid private key length")
            return SecureIdentity(
                identity_id,
                Ed25519PrivateKey.from_private_bytes(private_bytes),
            )
        except SecureIdentityStoreError:
            raise
        except Exception as error:
            raise SecureIdentityStoreError("protected agent identity could not be loaded") from error

    def _write(self, identity_id: str, protected: bytes) -> None:
        document = {
            "identity_id": identity_id,
            "protected_private_key": _encode(protected),
            "version": STORE_VERSION,
        }
        payload = json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        if len(payload) > MAX_STORE_BYTES:
            raise SecureIdentityStoreError("identity store payload is too large")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, self.path)
            except Exception:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
                raise
        except OSError as error:
            raise SecureIdentityStoreError("could not atomically write the protected identity") from error


def default_secure_identity_path() -> Path:
    """Return the user-local path without creating it or reading secrets."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Pipa" / "secure_agent_identity.json"
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / "AppData" / "Local" / "Pipa" / "secure_agent_identity.json"
    raise SecureIdentityStoreError("Windows user profile path is unavailable")
