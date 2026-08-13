import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trusted_unlock_protocol import (  # noqa: E402
    AuthorizationVerifier,
    create_signed_response,
)
from trusted_unlock_ticket import (  # noqa: E402
    ExpiredTicketError,
    TicketIssuer,
    TicketOperationError,
    TicketReplayError,
    UnknownTicketError,
)


class TrustedUnlockTicketTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self.verifier = AuthorizationVerifier(
            {"phone-main": self.private_key.public_key()},
            clock_skew_seconds=0,
        )
        self.issuer = TicketIssuer()

    def _authorized(self):
        challenge = self.verifier.create_challenge("phone-main", now=1000)
        response = create_signed_response(challenge, self.private_key)
        return self.verifier.verify_response(response, now=1001)

    def test_authorization_becomes_a_short_lived_one_use_ticket(self):
        authorization = self._authorized()

        ticket = self.issuer.issue(authorization, now=1001)
        consumed = self.issuer.consume(ticket.token, now=1002)

        self.assertEqual(consumed.device_id, "phone-main")
        self.assertEqual(consumed.operation, "unlock")
        self.assertEqual(self.issuer.pending_count, 0)

        with self.assertRaises(TicketReplayError):
            self.issuer.consume(ticket.token, now=1002)

    def test_ticket_expires_before_the_original_authorization(self):
        authorization = self._authorized()
        ticket = self.issuer.issue(authorization, now=1001, ttl_seconds=2)

        with self.assertRaises(ExpiredTicketError):
            self.issuer.consume(ticket.token, now=1003)

    def test_ticket_cannot_be_issued_at_authorization_expiry(self):
        authorization = replace(self._authorized(), expires_at=1001)

        with self.assertRaises(ExpiredTicketError):
            self.issuer.issue(authorization, now=1001)

    def test_ticket_cannot_be_used_for_another_operation(self):
        authorization = self._authorized()
        ticket = self.issuer.issue(authorization, now=1001)

        with self.assertRaises(TicketOperationError):
            self.issuer.consume(ticket.token, operation="other", now=1001)

    def test_unknown_token_is_rejected(self):
        with self.assertRaises(UnknownTicketError):
            self.issuer.consume("not-a-ticket", now=1000)

    def test_non_unlock_authorization_cannot_issue_a_ticket(self):
        authorization = replace(self._authorized(), operation="other")

        with self.assertRaises(TicketOperationError):
            self.issuer.issue(authorization, now=1001)

    def test_consumed_ticket_cache_is_bounded_and_replay_stays_rejected(self):
        with patch("trusted_unlock_ticket.MAX_CONSUMED_TICKETS", 1):
            first = self.issuer.issue(self._authorized(), now=1001)
            self.issuer.consume(first.token, now=1002)
            second = self.issuer.issue(self._authorized(), now=1001)
            self.issuer.consume(second.token, now=1002)

            self.assertEqual(len(self.issuer._consumed), 1)
            with self.assertRaises(UnknownTicketError):
                self.issuer.consume(first.token, now=1002)


if __name__ == "__main__":
    unittest.main()
