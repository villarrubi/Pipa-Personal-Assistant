"""In-memory timers that can be polled by a future device client."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass


MAX_TIMER_SECONDS = 7 * 24 * 60 * 60


@dataclass
class TimerRecord:
    timer_id: str
    label: str
    created_at: int
    due_at: int
    status: str
    _timer: threading.Timer

    def as_dict(self) -> dict[str, object]:
        return {
            "timer_id": self.timer_id,
            "label": self.label,
            "created_at": self.created_at,
            "due_at": self.due_at,
            "status": self.status,
        }


class TimerNotFoundError(ValueError):
    """The requested timer does not exist."""


class TimerManager:
    """Thread-safe, process-local timers; no persistence or hidden actions."""

    def __init__(self) -> None:
        self._timers: dict[str, TimerRecord] = {}
        self._lock = threading.RLock()

    def create(self, seconds: int, label: str = "Pipα timer") -> dict[str, object]:
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise ValueError("seconds debe ser un entero.")
        if seconds < 1 or seconds > MAX_TIMER_SECONDS:
            raise ValueError(f"seconds debe estar entre 1 y {MAX_TIMER_SECONDS}.")
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError("label debe tener entre 1 y 120 caracteres.")

        timer_id = secrets.token_urlsafe(8)
        created_at = int(time.time())
        timer = threading.Timer(seconds, self._fire, args=(timer_id,))
        timer.daemon = True
        record = TimerRecord(
            timer_id=timer_id,
            label=label.strip(),
            created_at=created_at,
            due_at=created_at + seconds,
            status="pending",
            _timer=timer,
        )
        with self._lock:
            self._timers[timer_id] = record
        timer.start()
        return record.as_dict()

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            return [record.as_dict() for record in self._timers.values()]

    def cancel(self, timer_id: str) -> dict[str, object]:
        with self._lock:
            record = self._timers.get(timer_id)
            if record is None:
                raise TimerNotFoundError("No existe ese temporizador.")
            if record.status == "pending":
                record._timer.cancel()
                record.status = "cancelled"
            return record.as_dict()

    def _fire(self, timer_id: str) -> None:
        with self._lock:
            record = self._timers.get(timer_id)
            if record is not None and record.status == "pending":
                record.status = "fired"
