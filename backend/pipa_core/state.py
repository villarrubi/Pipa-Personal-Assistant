"""Session and device UI state kept by the local core."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from .protocol import server_message


UI_STATES = frozenset({"idle", "listening", "thinking", "confirm", "speaking", "focus", "dashboard"})


@dataclass
class DeviceSession:
    session_id: str
    device_id: str
    connected_at: int
    state: str = "idle"
    caption: str | None = None
    focus_remaining: int | None = None

    def set_state(self, state: str, *, caption: str | None = None) -> None:
        if state not in UI_STATES:
            raise ValueError(f"unsupported UI state: {state}")
        self.state = state
        self.caption = caption

    def ui_message(self) -> dict[str, object]:
        return server_message(
            "ui_state",
            state=self.state,
            caption=self.caption,
            focus_remaining=self.focus_remaining,
        )


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, DeviceSession] = {}
        self._lock = threading.RLock()

    def create(self, device_id: str) -> DeviceSession:
        session = DeviceSession(
            session_id=secrets.token_urlsafe(16),
            device_id=device_id,
            connected_at=int(time.time()),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> DeviceSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
