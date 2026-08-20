"""Trusted-device registration for the future Pipa unlock protocol.

Only Ed25519 public keys are stored. The Windows implementation uses separate
64-bit HKLM registry locations for Trusted Unlock and future mobile commands,
so pairing and revocation require administrator permissions. The module has an
in-memory store for tests and development.
"""

from __future__ import annotations

import ctypes
import hashlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from trusted_unlock_protocol import (
    AuthorizationVerifier,
    public_key_from_base64,
    public_key_to_base64,
)

TRUSTED_UNLOCK_REGISTRY_PATH = r"SOFTWARE\Pipa\TrustedUnlock\Devices"
MOBILE_REGISTRY_PATH = r"SOFTWARE\Pipa\Mobile\Devices"
# Kept as a compatibility alias for callers that used the original constant.
REGISTRY_PATH = TRUSTED_UNLOCK_REGISTRY_PATH
PUBLIC_KEY_VALUE = "PublicKey"
CREATED_AT_VALUE = "CreatedAt"
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class DeviceStoreError(Exception):
    """Base class for device-store failures."""


class DeviceAlreadyRegisteredError(DeviceStoreError):
    """A device ID is already bound to a different public key."""


class DeviceNotFoundError(DeviceStoreError):
    """The requested device ID is not registered."""


@dataclass(frozen=True)
class RegisteredDevice:
    device_id: str
    public_key: str
    created_at: int

    @property
    def fingerprint(self) -> str:
        return public_key_fingerprint(self.public_key)


class DeviceStore(Protocol):
    def register(
        self,
        device_id: str,
        public_key: Ed25519PublicKey,
        *,
        created_at: int | None = None,
    ) -> RegisteredDevice: ...

    def revoke(self, device_id: str) -> None: ...

    def list_devices(self) -> list[RegisteredDevice]: ...

    def trusted_public_keys(self) -> dict[str, Ed25519PublicKey]: ...


def validate_device_id(device_id: str) -> str:
    if not isinstance(device_id, str) or DEVICE_ID_PATTERN.fullmatch(device_id) is None:
        raise ValueError(
            "device_id must start with a letter/number and contain only "
            "letters, numbers, '.', '_' or '-'; maximum 64 characters"
        )
    return device_id


def public_key_fingerprint(public_key_b64: str) -> str:
    public_key = public_key_from_base64(public_key_b64)
    raw_key = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    digest = hashlib.sha256(raw_key).hexdigest().upper()
    return ":".join(digest[index : index + 2] for index in range(0, len(digest), 2))


def is_administrator() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _is_registry_enumeration_end(error: OSError) -> bool:
    """Recognize only Win32's explicit end-of-enumeration condition."""

    return getattr(error, "winerror", None) == 259 or getattr(error, "errno", None) == 259


def _query_registry_value(winreg, key, value_name: str):
    """Read a registry value using the public winreg API.

    The test double historically exposes the value methods on the fake key,
    while real ``winreg`` exposes them as module functions.  Supporting both
    keeps the tests lightweight without relying on methods that real HKEY
    objects do not provide.
    """

    query_value = getattr(winreg, "QueryValueEx", None)
    if callable(query_value):
        return query_value(key, value_name)
    return key.QueryValueEx(value_name)


def _set_registry_value(winreg, key, value_name: str, value_type, value) -> None:
    """Write a registry value using the public winreg API or test double."""

    set_value = getattr(winreg, "SetValueEx", None)
    if callable(set_value):
        set_value(key, value_name, 0, value_type, value)
        return
    key.SetValueEx(value_name, 0, value_type, value)


class InMemoryDeviceStore:
    """Small store used by tests; it has no persistence or OS privileges."""

    def __init__(self) -> None:
        self._devices: dict[str, RegisteredDevice] = {}
        self._lock = threading.RLock()

    def register(
        self,
        device_id: str,
        public_key: Ed25519PublicKey,
        *,
        created_at: int | None = None,
    ) -> RegisteredDevice:
        validate_device_id(device_id)
        public_key_b64 = public_key_to_base64(public_key)
        record = RegisteredDevice(
            device_id=device_id,
            public_key=public_key_b64,
            created_at=int(time.time() if created_at is None else created_at),
        )

        with self._lock:
            existing = self._devices.get(device_id)
            if existing is not None and existing.public_key != public_key_b64:
                raise DeviceAlreadyRegisteredError(f"device ID is already bound to another key: {device_id}")
            if existing is not None:
                return existing
            self._devices[device_id] = record
            return record

    def revoke(self, device_id: str) -> None:
        validate_device_id(device_id)
        with self._lock:
            if device_id not in self._devices:
                raise DeviceNotFoundError(f"device is not registered: {device_id}")
            del self._devices[device_id]

    def list_devices(self) -> list[RegisteredDevice]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda item: item.device_id)

    def trusted_public_keys(self) -> dict[str, Ed25519PublicKey]:
        with self._lock:
            return {
                device.device_id: public_key_from_base64(device.public_key)
                for device in self._devices.values()
            }


class WindowsRegistryDeviceStore:
    """Persistent x64 HKLM store for trusted device public keys."""

    def __init__(self, registry_path: str = TRUSTED_UNLOCK_REGISTRY_PATH) -> None:
        if __import__("platform").system() != "Windows":
            raise DeviceStoreError("WindowsRegistryDeviceStore requires Windows")
        if not isinstance(registry_path, str) or not registry_path.strip():
            raise ValueError("registry_path must be non-empty text")
        import winreg

        self._winreg = winreg
        self._wow64 = winreg.KEY_WOW64_64KEY
        self._registry_path = registry_path.strip().strip("\\")

    def register(
        self,
        device_id: str,
        public_key: Ed25519PublicKey,
        *,
        created_at: int | None = None,
    ) -> RegisteredDevice:
        validate_device_id(device_id)
        public_key_b64 = public_key_to_base64(public_key)
        path = f"{self._registry_path}\\{device_id}"
        winreg = self._winreg

        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_LOCAL_MACHINE,
                path,
                0,
                winreg.KEY_READ | winreg.KEY_WRITE | self._wow64,
            )
        except PermissionError as error:
            raise DeviceStoreError("administrator permissions are required to pair a device") from error

        key_closed = False

        def close_key() -> None:
            nonlocal key_closed
            if key_closed:
                return
            try:
                key.Close()
            except OSError:
                # Do not replace the original persistence error with a close
                # failure. The registry provider will fail closed if the
                # entry cannot be read back completely.
                pass
            key_closed = True

        def remove_new_entry() -> bool:
            """Best-effort cleanup for a key created by this registration."""

            close_key()
            try:
                winreg.DeleteKeyEx(
                    winreg.HKEY_LOCAL_MACHINE,
                    path,
                    access=self._wow64,
                )
            except FileNotFoundError:
                return True
            except OSError:
                return False
            return True

        try:
            try:
                existing_key = _query_registry_value(winreg, key, PUBLIC_KEY_VALUE)[0]
            except FileNotFoundError:
                existing_key = None

            try:
                existing_created = _query_registry_value(winreg, key, CREATED_AT_VALUE)[0]
            except FileNotFoundError:
                existing_created = None

            if existing_key is not None and existing_key != public_key_b64:
                raise DeviceAlreadyRegisteredError(f"device ID is already bound to another key: {device_id}")

            if (existing_key is None) != (existing_created is None):
                # A valid entry is an all-or-nothing pair. Never silently
                # complete or overwrite a partially written registration:
                # manual revocation and an explicit re-pair should be needed
                # to repair a damaged store.
                raise DeviceStoreError("trusted device registration is incomplete")

            if existing_key is None:
                created_value = int(time.time() if created_at is None else created_at)
                try:
                    _set_registry_value(
                        winreg,
                        key,
                        PUBLIC_KEY_VALUE,
                        winreg.REG_SZ,
                        public_key_b64,
                    )
                    _set_registry_value(
                        winreg,
                        key,
                        CREATED_AT_VALUE,
                        winreg.REG_QWORD,
                        created_value,
                    )
                except (OSError, TypeError, ValueError) as error:
                    cleaned = remove_new_entry()
                    message = "could not persist trusted device registration"
                    if not cleaned:
                        message += "; incomplete registry entry could not be removed"
                    raise DeviceStoreError(message) from error
                return RegisteredDevice(device_id, public_key_b64, created_value)

            try:
                created = int(existing_created)
            except (TypeError, ValueError) as error:
                raise DeviceStoreError("trusted device registration is invalid") from error
            return RegisteredDevice(device_id, public_key_b64, created)
        except PermissionError as error:
            raise DeviceStoreError("administrator permissions are required to pair a device") from error
        except OSError as error:
            raise DeviceStoreError("could not read trusted device registration") from error
        finally:
            close_key()

    def revoke(self, device_id: str) -> None:
        validate_device_id(device_id)
        winreg = self._winreg
        path = f"{self._registry_path}\\{device_id}"

        try:
            winreg.DeleteKeyEx(
                winreg.HKEY_LOCAL_MACHINE,
                path,
                access=self._wow64,
            )
        except FileNotFoundError as error:
            raise DeviceNotFoundError(f"device is not registered: {device_id}") from error
        except PermissionError as error:
            raise DeviceStoreError("administrator permissions are required to revoke a device") from error

    def list_devices(self) -> list[RegisteredDevice]:
        winreg = self._winreg
        try:
            root = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                self._registry_path,
                0,
                winreg.KEY_READ | self._wow64,
            )
        except FileNotFoundError:
            return []

        devices: list[RegisteredDevice] = []
        try:
            index = 0
            while True:
                try:
                    device_id = winreg.EnumKey(root, index)
                except OSError as error:
                    if _is_registry_enumeration_end(error):
                        break
                    raise DeviceStoreError("could not enumerate trusted device store") from error
                index += 1
                try:
                    validate_device_id(device_id)
                    with winreg.OpenKey(root, device_id, 0, winreg.KEY_READ) as key:
                        public_key_b64 = str(_query_registry_value(winreg, key, PUBLIC_KEY_VALUE)[0])
                        created_at = int(_query_registry_value(winreg, key, CREATED_AT_VALUE)[0])
                    public_key_from_base64(public_key_b64)
                except (OSError, TypeError, ValueError) as error:
                    # A partial, corrupt or concurrently removed entry must
                    # never become a partially trusted snapshot or an
                    # uncaught traceback from the admin CLI.
                    raise DeviceStoreError("could not read trusted device store") from error
                devices.append(RegisteredDevice(device_id, public_key_b64, created_at))
        finally:
            root.Close()

        return sorted(devices, key=lambda item: item.device_id)

    def trusted_public_keys(self) -> dict[str, Ed25519PublicKey]:
        return {device.device_id: public_key_from_base64(device.public_key) for device in self.list_devices()}


class WindowsRegistryMobileDeviceStore(WindowsRegistryDeviceStore):
    """Separate x64 HKLM store for future mobile command identities.

    Keeping this path distinct prevents pairing an iPhone from implicitly
    granting it access to the experimental Trusted Unlock broker.
    """

    def __init__(self) -> None:
        super().__init__(MOBILE_REGISTRY_PATH)


def verifier_from_store(store: DeviceStore) -> AuthorizationVerifier:
    """Build a verifier from the current trusted public-key snapshot."""
    return AuthorizationVerifier(store.trusted_public_keys())
