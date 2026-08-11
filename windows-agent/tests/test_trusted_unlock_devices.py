import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trusted_unlock_devices import (  # noqa: E402
    DeviceAlreadyRegisteredError,
    DeviceNotFoundError,
    InMemoryDeviceStore,
    public_key_fingerprint,
    public_key_to_base64,
    verifier_from_store,
)
from trusted_unlock_protocol import create_signed_response  # noqa: E402


class TrustedUnlockDeviceStoreTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self.store = InMemoryDeviceStore()

    def test_register_is_idempotent_for_the_same_public_key(self):
        first = self.store.register(
            "phone-main",
            self.private_key.public_key(),
            created_at=1000,
        )
        second = self.store.register(
            "phone-main",
            self.private_key.public_key(),
            created_at=2000,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_devices()), 1)

    def test_register_rejects_replacing_a_key(self):
        self.store.register("phone-main", self.private_key.public_key())
        another_key = Ed25519PrivateKey.generate().public_key()

        with self.assertRaises(DeviceAlreadyRegisteredError):
            self.store.register("phone-main", another_key)

    def test_revoke_removes_device_from_verifier_snapshot(self):
        self.store.register("phone-main", self.private_key.public_key())
        self.store.revoke("phone-main")

        self.assertEqual(self.store.trusted_public_keys(), {})
        with self.assertRaises(DeviceNotFoundError):
            self.store.revoke("phone-main")

    def test_store_can_feed_the_challenge_verifier(self):
        self.store.register("phone-main", self.private_key.public_key())
        verifier = verifier_from_store(self.store)
        challenge = verifier.create_challenge("phone-main", now=1000)
        response = create_signed_response(challenge, self.private_key)

        result = verifier.verify_response(response, now=1001)

        self.assertEqual(result.device_id, "phone-main")

    def test_fingerprint_is_derived_from_the_public_key(self):
        encoded = public_key_to_base64(self.private_key.public_key())

        fingerprint = public_key_fingerprint(encoded)

        self.assertEqual(len(fingerprint), 95)
        self.assertTrue(all(char in "0123456789ABCDEF:" for char in fingerprint))


if __name__ == "__main__":
    unittest.main()
