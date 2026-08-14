"""Short-lived, one-use confirmations for outward-facing tools."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_CONFIRMATION_TTL = 30
MAX_PENDING_CONFIRMATIONS = 128
MAX_PENDING_PER_OWNER = 4


@dataclass(frozen=True)
class PendingConfirmation:
    confirmation_id: str
    owner_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    summary: str
    created_at: int
    expires_at: int
    call_id: str | None = None
    # Optional internal execution snapshot. It is intentionally omitted from
    # ``as_dict`` so a resolved phone, channel ID, or other private destination
    # cannot cross the confirmation transport.
    execution_arguments: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "confirmation_id": self.confirmation_id,
            "tool_name": self.tool_name,
            "summary": self.summary,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }
        if self.call_id is not None:
            result["call_id"] = self.call_id
        return result


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
        call_id: str | None = None,
        execution_arguments: Mapping[str, Any] | None = None,
    ) -> PendingConfirmation:
        if not isinstance(summary, str) or not summary.strip():
            raise ConfirmationError("confirmation summary must not be empty")
        if call_id is not None and (
            not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 128
        ):
            raise ConfirmationError("confirmation call_id is invalid")
        if execution_arguments is not None and not isinstance(execution_arguments, Mapping):
            raise ConfirmationError("confirmation execution arguments are invalid")
        if len(summary) > 240:
            summary = summary[:240]
        now = int(time.time())
        record = PendingConfirmation(
            confirmation_id=secrets.token_urlsafe(12),
            owner_id=owner_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            summary=summary[:240],
            created_at=now,
            expires_at=now + self._ttl_seconds,
            call_id=call_id,
            execution_arguments=(dict(execution_arguments) if execution_arguments is not None else None),
        )
        with self._lock:
            self._prune(now)
            if len(self._pending) >= MAX_PENDING_CONFIRMATIONS:
                raise ConfirmationError("too many pending confirmations")
            if owner_id is not None:
                owned = sum(record.owner_id == owner_id for record in self._pending.values())
                if owned >= MAX_PENDING_PER_OWNER:
                    raise ConfirmationError("too many pending confirmations for this session")
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
            if record is None or timestamp >= record.expires_at:
                raise ConfirmationError("confirmation is missing or expired")
            if record.owner_id is not None and record.owner_id != owner_id:
                raise ConfirmationError("confirmation belongs to another session")
            del self._pending[confirmation_id]
            return record

    def cancel_for_owner(self, owner_id: str) -> int:
        """Invalidate every outstanding action owned by a disconnected session."""

        if not isinstance(owner_id, str) or not owner_id:
            return 0
        with self._lock:
            cancelled = [key for key, record in self._pending.items() if record.owner_id == owner_id]
            for key in cancelled:
                del self._pending[key]
            return len(cancelled)

    def _prune(self, now: int) -> None:
        expired = [key for key, record in self._pending.items() if record.expires_at <= now]
        for key in expired:
            del self._pending[key]
