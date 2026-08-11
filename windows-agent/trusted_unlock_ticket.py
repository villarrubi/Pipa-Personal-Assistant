"""One-time authorization tickets for the future local IPC boundary.

Tickets represent an already verified authorization intent.  They are not
Windows credentials and this module does not call Winlogon or LogonUI.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from trusted_unlock_protocol import (
    UNLOCK_OPERATION,
    VerifiedAuthorization,
)


TICKET_TTL_SECONDS = 5
MAX_TICKET_TTL_SECONDS = 10


class TicketError(Exception):
    """Base class for expected ticket failures."""


class UnknownTicketError(TicketError):
    """The ticket is unknown or was already removed."""


class ExpiredTicketError(TicketError):
    """The ticket is no longer within its short validity window."""


class TicketReplayError(TicketError):
    """The ticket has already been consumed."""


class TicketOperationError(TicketError):
    """The requested operation does not match the ticket."""


@dataclass(frozen=True)
class IssuedTicket:
    """Opaque ticket handle plus non-secret diagnostic metadata."""

    token: str
    device_id: str
    operation: str
    issued_at: int
    expires_at: int


class TicketIssuer:
    """Create and consume short-lived, one-use authorization handles."""

    def __init__(self) -> None:
        self._tickets: dict[str, IssuedTicket] = {}
        self._consumed: dict[str, int] = {}
        self._lock = threading.RLock()

    def issue(
        self,
        authorization: VerifiedAuthorization,
        *,
        now: int | float | None = None,
        ttl_seconds: int = TICKET_TTL_SECONDS,
    ) -> IssuedTicket:
        if not isinstance(authorization, VerifiedAuthorization):
            raise TypeError("authorization must be VerifiedAuthorization")
        if authorization.operation != UNLOCK_OPERATION:
            raise TicketOperationError("only the unlock operation can issue a ticket")
        if ttl_seconds < 1 or ttl_seconds > MAX_TICKET_TTL_SECONDS:
            raise ValueError(
                f"ttl_seconds must be between 1 and {MAX_TICKET_TTL_SECONDS}"
            )

        issued_at = int(time.time() if now is None else now)
        if issued_at > authorization.expires_at:
            raise ExpiredTicketError("authorization is already expired")

        expires_at = min(issued_at + ttl_seconds, authorization.expires_at)
        ticket = IssuedTicket(
            token=secrets.token_urlsafe(32),
            device_id=authorization.device_id,
            operation=authorization.operation,
            issued_at=issued_at,
            expires_at=expires_at,
        )

        with self._lock:
            self._prune(issued_at)
            self._tickets[ticket.token] = ticket
        return ticket

    def consume(
        self,
        token: str,
        *,
        operation: str = UNLOCK_OPERATION,
        now: int | float | None = None,
    ) -> IssuedTicket:
        if not isinstance(token, str) or not token:
            raise UnknownTicketError("ticket token is empty")

        consumed_at = int(time.time() if now is None else now)

        with self._lock:
            if token in self._consumed:
                raise TicketReplayError("ticket was already consumed")

            ticket = self._tickets.get(token)
            if ticket is None:
                raise UnknownTicketError("ticket is unknown")
            if consumed_at > ticket.expires_at:
                del self._tickets[token]
                self._prune(consumed_at)
                raise ExpiredTicketError("ticket has expired")
            if operation != ticket.operation:
                raise TicketOperationError("ticket operation does not match")

            del self._tickets[token]
            self._consumed[token] = ticket.expires_at
            self._prune(consumed_at)
            return ticket

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._tickets)

    def _prune(self, now: int) -> None:
        expired = [
            token
            for token, ticket in self._tickets.items()
            if ticket.expires_at < now
        ]
        for token in expired:
            del self._tickets[token]

        expired_consumed = [
            token
            for token, expires_at in self._consumed.items()
            if expires_at < now
        ]
        for token in expired_consumed:
            del self._consumed[token]
