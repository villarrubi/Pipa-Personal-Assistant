import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secure_identity_store import SecureIdentityStoreError  # noqa: E402
from tools.mobile_config import inspect_mobile_transport  # noqa: E402


class MobileConfigTests(unittest.TestCase):
    def test_disabled_transport_is_safe_without_local_identity(self):
        result = inspect_mobile_transport({})

        self.assertTrue(result["success"])
        self.assertFalse(result["enabled"])
        self.assertFalse(result["listener_started"])
        self.assertEqual(result["issues"], [])

    @patch("tools.mobile_config.default_secure_identity_path", return_value=Path("missing-identity"))
    def test_partial_configuration_fails_closed(self, _identity_path):
        result = inspect_mobile_transport(
            {
                "PIPA_MOBILE_TRANSPORT": "tcp-v2",
                "PIPA_MOBILE_BIND": "0.0.0.0",
                "PIPA_MOBILE_PORT": "not-a-port",
            }
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["enabled"])
        self.assertGreaterEqual(len(result["issues"]), 2)
        self.assertFalse(result["listener_started"])

    @patch("tools.mobile_config.default_secure_identity_path")
    @patch("tools.mobile_config.SecureIdentityStore")
    @patch("tools.mobile_config.WindowsRegistryMobileDeviceStore")
    def test_valid_private_configuration_reports_scope_without_starting(
        self, device_store, identity_store, identity_path
    ):
        identity_path.return_value = Path(__file__)
        device_store.return_value.trusted_public_keys.return_value = {"iphone-main": object()}
        result = inspect_mobile_transport(
            {
                "PIPA_MOBILE_TRANSPORT": "tcp-v2",
                "PIPA_MOBILE_BIND": "192.168.1.20",
                "PIPA_MOBILE_PORT": "18765",
            }
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["bind_scope"], "private")
        self.assertTrue(result["identity_present"])
        self.assertTrue(result["identity_valid"])
        self.assertTrue(result["paired_devices_checked"])
        self.assertTrue(result["paired_devices_present"])
        self.assertFalse(result["listener_started"])
        identity_store.return_value.load.assert_called_once_with("pipa-agent-v2")

    @patch("tools.mobile_config.default_secure_identity_path", return_value=Path(__file__))
    @patch("tools.mobile_config.SecureIdentityStore")
    @patch("tools.mobile_config.WindowsRegistryMobileDeviceStore")
    def test_valid_network_without_pairing_fails_closed(self, device_store, identity_store, _identity_path):
        device_store.return_value.trusted_public_keys.return_value = {}
        result = inspect_mobile_transport(
            {
                "PIPA_MOBILE_TRANSPORT": "tcp-v2",
                "PIPA_MOBILE_BIND": "192.168.1.20",
                "PIPA_MOBILE_PORT": "18765",
            }
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["identity_valid"])
        self.assertTrue(result["paired_devices_checked"])
        self.assertFalse(result["paired_devices_present"])
        self.assertIn("no hay dispositivos móviles emparejados", result["issues"])

    @patch("tools.mobile_config.default_secure_identity_path", return_value=Path(__file__))
    @patch("tools.mobile_config.SecureIdentityStore")
    @patch("tools.mobile_config.WindowsRegistryMobileDeviceStore")
    def test_corrupt_identity_fails_closed_without_exposing_store_details(
        self, device_store, identity_store, _identity_path
    ):
        identity_store.return_value.load.side_effect = SecureIdentityStoreError("private DPAPI detail")
        device_store.return_value.trusted_public_keys.return_value = {"iphone-main": object()}

        result = inspect_mobile_transport(
            {
                "PIPA_MOBILE_TRANSPORT": "tcp-v2",
                "PIPA_MOBILE_BIND": "192.168.1.20",
                "PIPA_MOBILE_PORT": "18765",
            }
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["identity_present"])
        self.assertFalse(result["identity_valid"])
        self.assertIn("la identidad segura no se pudo validar", result["issues"])
        self.assertNotIn("private DPAPI detail", str(result))


if __name__ == "__main__":
    unittest.main()
