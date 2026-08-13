import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from tools.contacts import (
    MAX_CONFIG_FILE_BYTES,
    ContactsConfigError,
    load_contacts,
    resolve_discord_contact,
    resolve_whatsapp_contact,
    validate_contacts,
)


class ContactsTests(unittest.TestCase):
    def test_validates_and_resolves_local_destinations(self):
        contacts = validate_contacts(
            {
                "Mamá": {
                    "aliases": ["mama", "madre"],
                    "whatsapp_phone": "+34 600 123 456",
                    "discord_channel_id": "12345678901234567",
                }
            }
        )

        self.assertEqual(contacts["mama"].whatsapp_phone, "34600123456")
        self.assertEqual(contacts["mama"].discord_channel_id, "12345678901234567")

    def test_rejects_duplicate_aliases_and_empty_destinations(self):
        with self.assertRaises(ContactsConfigError):
            validate_contacts(
                {
                    "one": {"aliases": ["same"], "whatsapp_phone": "+34600123456"},
                    "two": {"aliases": ["same"], "discord_channel_id": "12345678901234567"},
                }
            )
        with self.assertRaises(ContactsConfigError):
            validate_contacts(
                {
                    "amigo\u202e": {
                        "aliases": ["amigo"],
                        "whatsapp_phone": "+34600123456",
                    }
                }
            )
        with self.assertRaises(ContactsConfigError):
            validate_contacts({"empty": {"aliases": ["empty"]}})
        with self.assertRaises(ContactsConfigError):
            validate_contacts(
                {
                    "Mamá": {"whatsapp_phone": "+34600123456"},
                    "mama": {"discord_channel_id": "12345678901234567"},
                }
            )

    def test_resolution_reads_only_the_local_ignored_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.local.json"
            path.write_text(
                json.dumps(
                    {
                        "amiga": {
                            "whatsapp_phone": "+34600123456",
                            "discord_channel_id": "12345678901234567",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch("tools.contacts.LOCAL_CONTACTS_FILE", path):
                self.assertEqual(resolve_whatsapp_contact("AMIGA"), ("amiga", "34600123456"))
                self.assertEqual(
                    resolve_discord_contact("amiga"),
                    ("amiga", "12345678901234567", None),
                )

    def test_missing_local_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("tools.contacts.LOCAL_CONTACTS_FILE", Path(directory) / "missing.json"):
                with self.assertRaises(ValueError):
                    resolve_whatsapp_contact("amiga")

    def test_contact_file_size_is_bounded_before_json_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.local.json"
            path.write_text("{" + " " * MAX_CONFIG_FILE_BYTES + "}", encoding="utf-8")
            with patch("tools.contacts.LOCAL_CONTACTS_FILE", path):
                with self.assertRaises(ContactsConfigError):
                    load_contacts()

    def test_contact_file_rejects_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.local.json"
            path.write_bytes(b"\xff")
            with patch("tools.contacts.LOCAL_CONTACTS_FILE", path):
                with self.assertRaises(ContactsConfigError):
                    load_contacts()


if __name__ == "__main__":
    unittest.main()
