import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.readiness import inspect_contacts, inspect_readiness  # noqa: E402


class ReadinessTests(unittest.TestCase):
    @patch("tools.readiness.load_contacts", return_value={})
    def test_contact_report_is_empty_without_local_aliases(self, load_contacts):
        result = inspect_contacts()

        self.assertEqual(
            result,
            {
                "success": True,
                "configured_count": 0,
                "whatsapp_destinations": 0,
                "discord_destinations": 0,
            },
        )
        load_contacts.assert_called_once_with()

    @patch("tools.readiness.load_contacts")
    def test_contact_report_exposes_counts_but_not_destinations(self, load_contacts):
        load_contacts.return_value = {
            "mama": SimpleNamespace(whatsapp_phone="34600000000", discord_channel_id=None),
            "amigo": SimpleNamespace(whatsapp_phone=None, discord_channel_id="12345678901234567"),
        }

        result = inspect_contacts()
        serialized = json.dumps(result)

        self.assertEqual(result["configured_count"], 2)
        self.assertEqual(result["whatsapp_destinations"], 1)
        self.assertEqual(result["discord_destinations"], 1)
        self.assertNotIn("34600000000", serialized)
        self.assertNotIn("12345678901234567", serialized)

    @patch("tools.readiness.get_integration_capabilities", return_value={"whatsapp": {"available": True}})
    @patch(
        "tools.readiness.inspect_contacts",
        return_value={
            "success": True,
            "configured_count": 1,
            "whatsapp_destinations": 1,
            "discord_destinations": 0,
        },
    )
    @patch(
        "tools.readiness.inspect_apps",
        return_value={
            "success": True,
            "ready": True,
            "configured_count": 2,
            "unresolved_count": 0,
            "apps": {},
        },
    )
    def test_readiness_joins_safe_reports(self, inspect_apps, inspect_contacts, get_capabilities):
        result = inspect_readiness()

        self.assertTrue(result["success"])
        self.assertEqual(result["apps"]["configured_count"], 2)
        self.assertEqual(result["contacts"]["whatsapp_destinations"], 1)
        self.assertEqual(result["integrations"], {"whatsapp": {"available": True}})
        inspect_apps.assert_called_once_with()
        inspect_contacts.assert_called_once_with()
        get_capabilities.assert_called_once_with()

    @patch("tools.readiness.get_integration_capabilities", side_effect=ValueError("private details"))
    @patch("tools.readiness.inspect_contacts", return_value={"success": True})
    @patch("tools.readiness.inspect_apps", return_value={"success": True, "ready": True})
    def test_readiness_fails_closed_without_echoing_adapter_errors(
        self, inspect_apps, inspect_contacts, get_capabilities
    ):
        result = inspect_readiness()

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "integrations_unavailable")
        self.assertNotIn("private details", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
