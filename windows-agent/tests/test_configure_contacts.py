import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from configure_contacts import build_contact_payload, main  # noqa: E402


class ConfigureContactsTests(unittest.TestCase):
    def test_build_contact_payload_replaces_same_name_and_preserves_others(self):
        result = build_contact_payload(
            name="Mamá",
            aliases=["madre"],
            whatsapp_phone="+34 600 123 456",
            existing={
                "mama": {"aliases": ["viejo"], "whatsapp_phone": "+34600000001"},
                "amigo": {"aliases": ["colega"], "discord_channel_id": "12345678901234567"},
            },
        )

        self.assertNotIn("mama", result)
        self.assertEqual(result["Mamá"]["aliases"], ["madre"])
        self.assertEqual(result["amigo"]["discord_channel_id"], "12345678901234567")

    def test_main_validates_without_writing_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.local.json"
            with patch("configure_contacts.LOCAL_CONTACTS_FILE", path):
                result = main(
                    [
                        "--name",
                        "mama",
                        "--whatsapp-phone",
                        "+34600123456",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertFalse(path.exists())

    def test_main_writes_atomic_validated_payload_only_with_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.local.json"
            with patch("configure_contacts.LOCAL_CONTACTS_FILE", path):
                result = main(
                    [
                        "--name",
                        "amigo",
                        "--alias",
                        "colega",
                        "--discord-channel-id",
                        "12345678901234567",
                        "--write",
                    ]
                )

                self.assertEqual(result, 0)
                with path.open("r", encoding="utf-8") as file:
                    raw = json.load(file)
                self.assertEqual(raw["amigo"]["discord_channel_id"], "12345678901234567")
                self.assertEqual(list(path.parent.glob(".contacts.*.tmp")), [])

    def test_invalid_contact_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.local.json"
            with patch("configure_contacts.LOCAL_CONTACTS_FILE", path):
                result = main(
                    [
                        "--name",
                        "amigo",
                        "--whatsapp-phone",
                        "not-a-phone",
                        "--write",
                    ]
                )

            self.assertEqual(result, 1)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
