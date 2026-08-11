"""Allowlisted Windows media-key actions."""

from __future__ import annotations

import ctypes
import platform


MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
}
KEYEVENTF_KEYUP = 0x0002


def send_media_action(action: str) -> dict[str, object]:
    if action not in MEDIA_KEYS:
        allowed = ", ".join(sorted(MEDIA_KEYS))
        raise ValueError(f"Acción multimedia no permitida. Usa: {allowed}.")
    if platform.system() != "Windows":
        raise RuntimeError("El control multimedia requiere Windows.")

    user32 = ctypes.windll.user32
    virtual_key = MEDIA_KEYS[action]
    user32.keybd_event(virtual_key, 0, 0, 0)
    user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)
    return {"success": True, "action": action}
