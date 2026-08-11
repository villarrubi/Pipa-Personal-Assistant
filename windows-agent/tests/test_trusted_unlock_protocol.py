import sys
import unittest
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trusted_unlock_protocol import (  # noqa: E402
    MAX_PENDING_PER_DEVICE,
    AuthorizationVerifier,
    ChallengeLimitError,
    ChallengeMismatchError,
    ExpiredChallengeError,
    InvalidResponseError,
    ReplayDetectedError,
    UnknownChallengeError,
    UnknownDeviceError,
    create_signed_response,
)


class TrustedUnlockProtocolTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self.verifier = AuthorizationVerifier(
            {"phone-main": self.private_key.public_key()},
            clock_skew_seconds=0,
        )

    def test_valid_response_is_accepted_once(self):
        challenge = self.verifier.create_challenge("phone-main", now=1000)
        response = create_signed_response(challenge, self.private_key)

        result = self.verifier.verify_response(response, now=1001)

        self.assertEqual(result.device_id, "phone-main")
        self.assertEqual(result.operation, "unlock")
        self.assertEqual(self.verifier.pending_count, 0)

        with self.assertRaises(ReplayDetectedError):
            self.verifier.verify_response(response, now=1001)

    def test_signature_is_bound_to_the_exact_challenge(self):
        challenge = self.verifier.create_challenge("phone-main", now=1000)
        altered = replace(challenge, operation="different-operation")
        response = create_signed_response(altered, self.private_key)
        response = replace(response, challenge_id=challenge.challenge_id)

        with self.assertRaises(InvalidResponseError):
            self.verifier.verify_response(response, now=1000)

    def test_expired_challenge_is_rejected(self):
        challenge = self.verifier.create_challenge(
            "phone-main",
            now=1000,
            ttl_seconds=5,
        )
        response = create_signed_response(challenge, self.private_key)

        with self.assertRaises(ExpiredChallengeError):
            self.verifier.verify_response(response, now=1006)

    def test_response_cannot_change_the_device_binding(self):
        challenge = self.verifier.create_challenge("phone-main", now=1000)
        response = create_signed_response(challenge, self.private_key)
        response = replace(response, device_id="another-device")

        with self.assertRaises(ChallengeMismatchError):
            self.verifier.verify_response(response, now=1000)

    def test_revoked_device_cannot_complete_pending_challenge(self):
        challenge = self.verifier.create_challenge("phone-main", now=1000)
        self.verifier.revoke_device("phone-main")
        response = create_signed_response(challenge, self.private_key)

        with self.assertRaises(UnknownDeviceError):
            self.verifier.verify_response(response, now=1000)

    def test_unknown_device_cannot_receive_a_challenge(self):
        with self.assertRaises(UnknownDeviceError):
            self.verifier.create_challenge("unknown-device", now=1000)

    def test_unknown_challenge_is_rejected(self):
        challenge = self.verifier.create_challenge("phone-main", now=1000)
        response = create_signed_response(challenge, self.private_key)
        self.verifier = AuthorizationVerifier(
            {"phone-main": self.private_key.public_key()},
            clock_skew_seconds=0,
        )

        with self.assertRaises(UnknownChallengeError):
            self.verifier.verify_response(response, now=1000)

    def test_pending_challenges_are_bounded_per_device(self):
        for _ in range(MAX_PENDING_PER_DEVICE):
            self.verifier.create_challenge("phone-main", now=1000)

        with self.assertRaises(ChallengeLimitError):
            self.verifier.create_challenge("phone-main", now=1000)


if __name__ == "__main__":
    unittest.main()
