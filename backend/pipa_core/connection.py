"""Transport-independent lifecycle for one authenticated Pipa connection."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from trusted_unlock_protocol import TrustedUnlockError

from .core import PipaCore
from .protocol import ClientMessage, server_message

MAX_AUTH_FAILURES = 3
MIN_CHALLENGE_INTERVAL_SECONDS = 1.0
SESSION_IDLE_SECONDS = 10 * 60


@dataclass(frozen=True)
class ConnectionResult:
    responses: list[dict[str, Any]]
    close: bool = False


class AuthenticatedConnection:
    """Authentication, rate limits and session cleanup shared by transports."""

    def __init__(self, core: PipaCore, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.core = core
        self.clock = clock
        self.session_id: str | None = None
        self.auth_failures = 0
        self.last_challenge_at: float | None = None
        self.last_activity_at = clock()

    def process(self, message: ClientMessage) -> ConnectionResult:
        self.last_activity_at = self.clock()
        if message.type == "challenge_request":
            return self._challenge(message)
        if self.session_id is None:
            return self._authenticate(message)
        if message.type == "hello":
            return ConnectionResult([server_message("error", code="already_authenticated")])
        return ConnectionResult(self.core.handle(self.session_id, message))

    def idle(self) -> bool:
        return self.clock() - self.last_activity_at > SESSION_IDLE_SECONDS

    def close(self) -> None:
        if self.session_id is not None:
            self.core.close(self.session_id)
            self.session_id = None

    def _challenge(self, message: ClientMessage) -> ConnectionResult:
        if self.session_id is not None:
            return ConnectionResult([server_message("error", code="already_authenticated")])

        now = self.clock()
        if (
            self.last_challenge_at is not None
            and now - self.last_challenge_at < MIN_CHALLENGE_INTERVAL_SECONDS
        ):
            return ConnectionResult([server_message("error", code="rate_limited")])
        self.last_challenge_at = now

        try:
            challenge = self.core.create_challenge(message.fields["device_id"])
        except (TrustedUnlockError, ValueError):
            return self._authentication_failure()
        return ConnectionResult([server_message("challenge", challenge=challenge.as_dict())])

    def _authenticate(self, message: ClientMessage) -> ConnectionResult:
        if message.type != "hello":
            return ConnectionResult([server_message("error", code="authentication_required")])
        try:
            session = self.core.authenticate(
                message.fields["device_id"],
                message.fields["challenge_id"],
                message.fields["signature"],
                firmware_version=message.fields.get("firmware_version"),
                capabilities=message.fields.get("capabilities"),
            )
        except (TrustedUnlockError, ValueError):
            return self._authentication_failure()

        self.session_id = session.session_id
        self.auth_failures = 0
        return ConnectionResult(
            [server_message("ready", session_id=session.session_id, ui_state=session.ui_message())]
        )

    def _authentication_failure(self) -> ConnectionResult:
        self.auth_failures += 1
        return ConnectionResult(
            [server_message("error", code="authentication_failed")],
            close=self.auth_failures >= MAX_AUTH_FAILURES,
        )
