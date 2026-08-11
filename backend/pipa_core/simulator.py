"""Ephemeral device simulator for exercising the Pipa Core before hardware."""

from __future__ import annotations

from typing import Any

from trusted_unlock_devices import InMemoryDeviceStore, verifier_from_store
from trusted_unlock_simulator import InMemoryTrustedDevice

from .core import PipaCore
from .protocol import PROTOCOL_VERSION, parse_client_message
from .tools import ToolCatalog, ToolRouter


class DeviceSimulator:
    """A test-only device identity; its private key never leaves memory."""

    def __init__(self, core_factory) -> None:
        self.device = InMemoryTrustedDevice.generate("simulator")
        store = InMemoryDeviceStore()
        store.register(self.device.device_id, self.device.public_key)
        self.core = core_factory(verifier_from_store(store))
        challenge = self.core.create_challenge(self.device.device_id)
        session = self.core.authenticate(
            self.device.device_id,
            challenge.challenge_id,
            self.device.sign(challenge).signature,
        )
        self.session_id = session.session_id

    def send(self, message_type: str, **fields: Any) -> list[dict[str, Any]]:
        payload = {"protocol_version": PROTOCOL_VERSION, "type": message_type, **fields}
        return self.core.handle(self.session_id, parse_client_message(payload))


def create_simulator(catalog: ToolCatalog) -> DeviceSimulator:
    return DeviceSimulator(lambda verifier: PipaCore(verifier, ToolRouter(catalog)))
