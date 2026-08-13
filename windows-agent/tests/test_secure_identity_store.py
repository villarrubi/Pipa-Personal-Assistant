import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secure_identity_store import SecureIdentityStore, SecureIdentityStoreError  # noqa: E402


class SecureIdentityStoreTests(unittest.TestCase):
    def test_round_trip_uses_protected_bytes_and_keeps_identity_stable(self):
        protected_values = []

        def protect(value):
            protected = b"dpapi:" + value
            protected_values.append(protected)
            return protected

        def unprotect(value):
            self.assertTrue(value.startswith(b"dpapi:"))
            return value[len(b"dpapi:") :]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            first = SecureIdentityStore(path, protect=protect, unprotect=unprotect).load_or_create(
                "pipa-agent"
            )
            second = SecureIdentityStore(path, protect=protect, unprotect=unprotect).load_or_create(
                "pipa-agent"
            )

            self.assertEqual(first.public_key_b64, second.public_key_b64)
            self.assertEqual(len(protected_values), 1)
            self.assertNotIn(first.private_key.private_bytes_raw(), path.read_bytes())

    def test_wrong_identity_id_and_duplicate_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            store = SecureIdentityStore(
                path, protect=lambda value: b"p" + value, unprotect=lambda value: value[1:]
            )
            store.load_or_create("pipa-agent")
            with self.assertRaises(SecureIdentityStoreError):
                store.load_or_create("another-agent")

            path.write_text(
                '{"identity_id":"pipa-agent","identity_id":"pipa-agent",'
                '"protected_private_key":"cA","version":1}',
                encoding="utf-8",
            )
            with self.assertRaises(SecureIdentityStoreError):
                store.load_or_create("pipa-agent")

    def test_malformed_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(json.dumps({"version": 2}), encoding="utf-8")
            store = SecureIdentityStore(path)
            with self.assertRaises(SecureIdentityStoreError):
                store.load_or_create("pipa-agent")

    def test_noncanonical_protected_key_encoding_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(
                json.dumps(
                    {
                        "identity_id": "pipa-agent",
                        "protected_private_key": "cB",
                        "version": 1,
                    }
                ),
                encoding="utf-8",
            )
            store = SecureIdentityStore(path, unprotect=lambda value: value)

            with self.assertRaises(SecureIdentityStoreError):
                store.load("pipa-agent")

    def test_load_does_not_create_a_missing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            store = SecureIdentityStore(path, protect=lambda value: value, unprotect=lambda value: value)

            with self.assertRaises(SecureIdentityStoreError):
                store.load("pipa-agent")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
