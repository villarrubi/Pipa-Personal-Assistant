"""Trusted-device registration for the future Pipa unlock protocol.

Only Ed25519 public keys are stored.  The Windows implementation uses a
64-bit HKLM registry location so pairing and revocation require administrator
permissions.  The module has an in-memory store for tests and development.
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

REGISTRY_PATH = r"SOFTWARE\Pipa\TrustedUnlock\Devices"
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

    def __init__(self) -> None:
        if __import__("platform").system() != "Windows":
            raise DeviceStoreError("WindowsRegistryDeviceStore requires Windows")
        import winreg

        self._winreg = winreg
        self._wow64 = winreg.KEY_WOW64_64KEY

    def register(
        self,
        device_id: str,
        public_key: Ed25519PublicKey,
        *,
        created_at: int | None = None,
    ) -> RegisteredDevice:
        validate_device_id(device_id)
        public_key_b64 = public_key_to_base64(public_key)
        path = f"{REGISTRY_PATH}\\{device_id}"
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

        try:
            try:
                existing_key = key.QueryValueEx(PUBLIC_KEY_VALUE)[0]
            except FileNotFoundError:
                existing_key = None

            if existing_key is not None and existing_key != public_key_b64:
                raise DeviceAlreadyRegisteredError(f"device ID is already bound to another key: {device_id}")

            if existing_key is None:
                key.SetValueEx(
                    PUBLIC_KEY_VALUE,
                    0,
                    winreg.REG_SZ,
                    public_key_b64,
                )
                key.SetValueEx(
                    CREATED_AT_VALUE,
                    0,
                    winreg.REG_QWORD,
                    int(time.time() if created_at is None else created_at),
                )

            created = int(key.QueryValueEx(CREATED_AT_VALUE)[0])
            return RegisteredDevice(device_id, public_key_b64, created)
        finally:
            key.Close()

    def revoke(self, device_id: str) -> None:
        validate_device_id(device_id)
        winreg = self._winreg
        path = f"{REGISTRY_PATH}\\{device_id}"

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
                REGISTRY_PATH,
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
                except OSError:
                    break
                index += 1
                validate_device_id(device_id)

                with winreg.OpenKey(root, device_id, 0, winreg.KEY_READ) as key:
                    public_key_b64 = str(key.QueryValueEx(PUBLIC_KEY_VALUE)[0])
                    created_at = int(key.QueryValueEx(CREATED_AT_VALUE)[0])
                public_key_from_base64(public_key_b64)
                devices.append(RegisteredDevice(device_id, public_key_b64, created_at))
        finally:
            root.Close()

        return sorted(devices, key=lambda item: item.device_id)

    def trusted_public_keys(self) -> dict[str, Ed25519PublicKey]:
        return {device.device_id: public_key_from_base64(device.public_key) for device in self.list_devices()}


def verifier_from_store(store: DeviceStore) -> AuthorizationVerifier:
    """Build a verifier from the current trusted public-key snapshot."""
    return AuthorizationVerifier(store.trusted_public_keys())
