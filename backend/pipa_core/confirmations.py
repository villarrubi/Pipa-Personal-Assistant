"""Short-lived, one-use confirmations for outward-facing tools."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_CONFIRMATION_TTL = 30


@dataclass(frozen=True)
class PendingConfirmation:
    confirmation_id: str
    owner_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    summary: str
    created_at: int
    expires_at: int

    def as_dict(self) -> dict[str, object]:
        return {
            "confirmation_id": self.confirmation_id,
            "tool_name": self.tool_name,
            "summary": self.summary,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


class ConfirmationError(ValueError):
    """A confirmation is missing, expired, or already consumed."""


class ConfirmationManager:
    def __init__(self, *, ttl_seconds: int = DEFAULT_CONFIRMATION_TTL) -> None:
        if ttl_seconds < 1 or ttl_seconds > 300:
            raise ValueError("confirmation TTL must be between 1 and 300 seconds")
        self._ttl_seconds = ttl_seconds
        self._pending: dict[str, PendingConfirmation] = {}
        self._lock = threading.RLock()

    def create(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        summary: str,
        *,
        owner_id: str | None = None,
    ) -> PendingConfirmation:
        now = int(time.time())
        record = PendingConfirmation(
            confirmation_id=secrets.token_urlsafe(12),
            owner_id=owner_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            summary=summary[:240],
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._prune(now)
            self._pending[record.confirmation_id] = record
        return record

    def consume(
        self,
        confirmation_id: str,
        *,
        owner_id: str | None = None,
        now: int | None = None,
    ) -> PendingConfirmation:
        timestamp = int(time.time() if now is None else now)
        with self._lock:
            record = self._pending.get(confirmation_id)
            if record is None or timestamp > record.expires_at:
                raise ConfirmationError("confirmation is missing or expired")
            if record.owner_id is not None and record.owner_id != owner_id:
                raise ConfirmationError("confirmation belongs to another session")
            del self._pending[confirmation_id]
            return record

    def _prune(self, now: int) -> None:
        expired = [key for key, record in self._pending.items() if record.expires_at < now]
        for key in expired:
            del self._pending[key]
