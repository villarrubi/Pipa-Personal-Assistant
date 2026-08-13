"""Session and device UI state kept by the local core."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from .protocol import server_message

UI_STATES = frozenset({"idle", "listening", "thinking", "confirm", "speaking", "focus", "dashboard"})
MAX_SESSIONS = 32
MAX_SESSIONS_PER_DEVICE = 2


class SessionLimitError(ValueError):
    """The core cannot accept another authenticated session right now."""


@dataclass
class DeviceSession:
    session_id: str
    device_id: str
    connected_at: int
    state: str = "idle"
    caption: str | None = None
    focus_remaining: int | None = None
    firmware_version: str | None = None
    capabilities: tuple[str, ...] = ()
    capabilities_initialized: bool = True
    last_seen_at: int | None = None
    audio_state: str | None = None
    battery_percent: int | None = None
    wifi_rssi: int | None = None

    def touch(self) -> None:
        self.last_seen_at = int(time.time())

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

    def create(
        self,
        device_id: str,
        *,
        firmware_version: str | None = None,
        capabilities: tuple[str, ...] = (),
        capabilities_initialized: bool = True,
    ) -> DeviceSession:
        now = int(time.time())
        session = DeviceSession(
            session_id=secrets.token_urlsafe(16),
            device_id=device_id,
            connected_at=now,
            firmware_version=firmware_version,
            capabilities=capabilities,
            capabilities_initialized=capabilities_initialized,
            last_seen_at=now,
        )
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise SessionLimitError("too many authenticated sessions")
            sessions_for_device = sum(existing.device_id == device_id for existing in self._sessions.values())
            if sessions_for_device >= MAX_SESSIONS_PER_DEVICE:
                raise SessionLimitError("too many sessions for this device")
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
