import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.protocol import parse_client_message  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolRouter  # noqa: E402
from pipa_serial_gateway import SerialGateway  # noqa: E402
from trusted_unlock_devices import InMemoryDeviceStore, verifier_from_store  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402
from trusted_unlock_protocol import Challenge  # noqa: E402


class SerialGatewayTests(unittest.TestCase):
    def setUp(self):
        device = InMemoryTrustedDevice.generate("waveshare-01")
        store = InMemoryDeviceStore()
        store.register(device.device_id, device.public_key)
        self.device = device
        self.core = PipaCore(verifier_from_store(store), ToolRouter(ToolCatalog([])))
        self.gateway = SerialGateway(self.core, "COM99")

    def test_challenge_request_then_signed_hello(self):
        request = parse_client_message(
            {"protocol_version": 1, "type": "challenge_request", "device_id": "waveshare-01"}
        )
        outputs, session_id = self.gateway._handle(request, None)
        self.assertIsNone(session_id)
        challenge = outputs[0]["challenge"]

        signed = self.device.sign(Challenge(**challenge))
        hello = parse_client_message(
            {
                "protocol_version": 1,
                "type": "hello",
                "device_id": "waveshare-01",
                "challenge_id": signed.challenge_id,
                "signature": signed.signature,
            }
        )
        outputs, session_id = self.gateway._handle(hello, None)
        self.assertIsNotNone(session_id)
        self.assertEqual(outputs[0]["type"], "ready")


if __name__ == "__main__":
    unittest.main()
