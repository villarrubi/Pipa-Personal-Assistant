"""Ephemeral device simulator for exercising the Pipa Core before hardware."""

from __future__ import annotations

from typing import Any

from trusted_unlock_devices import InMemoryDeviceStore, verifier_from_store
from trusted_unlock_protocol import Challenge
from trusted_unlock_simulator import InMemoryTrustedDevice

from .connection import AuthenticatedConnection
from .core import PipaCore
from .protocol import PROTOCOL_VERSION, parse_client_message
from .tools import ToolCatalog, ToolRouter


class DeviceSimulator:
    """A test-only device identity; its private key never leaves memory."""

    def __init__(self, core_factory, *, capabilities: list[str] | tuple[str, ...] | None = None) -> None:
        self.device = InMemoryTrustedDevice.generate("simulator")
        self.capabilities = tuple(capabilities or ())
        store = InMemoryDeviceStore()
        store.register(self.device.device_id, self.device.public_key)
        self.core = core_factory(verifier_from_store(store))
        self.connection = AuthenticatedConnection(self.core)
        challenge_result = self.connection.process(
            parse_client_message(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "challenge_request",
                    "device_id": self.device.device_id,
                }
            )
        )
        challenge_fields = next(
            item["challenge"] for item in challenge_result.responses if item["type"] == "challenge"
        )
        signed = self.device.sign(Challenge(**challenge_fields))
        ready_result = self.connection.process(
            parse_client_message(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "hello",
                    "device_id": self.device.device_id,
                    "challenge_id": signed.challenge_id,
                    "signature": signed.signature,
                    "capabilities": list(self.capabilities),
                }
            )
        )
        if self.connection.session_id is None or not any(
            item["type"] == "ready" for item in ready_result.responses
        ):
            raise RuntimeError("simulator authentication failed")
        self.session_id = self.connection.session_id

    def send(self, message_type: str, **fields: Any) -> list[dict[str, Any]]:
        payload = {"protocol_version": PROTOCOL_VERSION, "type": message_type, **fields}
        return self.connection.process(parse_client_message(payload)).responses

    def close(self) -> None:
        """Close the simulated transport and invalidate its session."""

        self.connection.close()


def create_simulator(
    catalog: ToolCatalog,
    *,
    capabilities: list[str] | tuple[str, ...] | None = None,
) -> DeviceSimulator:
    return DeviceSimulator(
        lambda verifier: PipaCore(verifier, ToolRouter(catalog)),
        capabilities=capabilities,
    )
