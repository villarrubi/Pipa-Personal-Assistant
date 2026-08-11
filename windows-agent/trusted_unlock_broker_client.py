"""Minimal client for the local Trusted Unlock named pipe."""

from __future__ import annotations

import json
import secrets
from typing import Any

from trusted_unlock_broker import MAX_MESSAGE_BYTES, PIPE_NAME, PROTOCOL_VERSION


class BrokerClientError(Exception):
    """The broker could not be reached or rejected the request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class WindowsNamedPipeBrokerClient:
    """Send bounded JSON requests to the local broker."""

    def __init__(self, *, pipe_name: str = PIPE_NAME, timeout_ms: int = 5000) -> None:
        if timeout_ms < 1 or timeout_ms > 60_000:
            raise ValueError("timeout_ms must be between 1 and 60000")
        self._pipe_name = pipe_name
        self._timeout_ms = timeout_ms

    def request(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
        if not isinstance(command, str) or not command:
            raise ValueError("command must be a non-empty string")
        request = {
            "version": PROTOCOL_VERSION,
            "request_id": secrets.token_hex(8),
            "command": command,
            "payload": payload or {},
        }
        encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ValueError("request is too large")

        import pywintypes
        import win32con
        import win32file
        import win32pipe

        try:
            win32pipe.WaitNamedPipe(self._pipe_name, self._timeout_ms)
            handle = win32file.CreateFile(
                self._pipe_name,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                0,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )
            win32pipe.SetNamedPipeHandleState(
                handle,
                win32pipe.PIPE_READMODE_MESSAGE,
                None,
                None,
            )
        except pywintypes.error as error:
            raise BrokerClientError("pipe_unavailable", "broker pipe is unavailable") from error

        try:
            win32file.WriteFile(handle, encoded)
            _, raw_response = win32file.ReadFile(handle, MAX_MESSAGE_BYTES + 1)
        except pywintypes.error as error:
            raise BrokerClientError("pipe_error", "broker pipe communication failed") from error
        finally:
            win32file.CloseHandle(handle)

        if len(raw_response) > MAX_MESSAGE_BYTES:
            raise BrokerClientError("invalid_response", "broker response is too large")
        try:
            response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BrokerClientError("invalid_response", "broker response is invalid") from error

        if not isinstance(response, dict) or response.get("ok") is not True:
            error_data = response.get("error", {}) if isinstance(response, dict) else {}
            code = error_data.get("code", "broker_error") if isinstance(error_data, dict) else "broker_error"
            message = error_data.get("message", "request rejected") if isinstance(error_data, dict) else "request rejected"
            raise BrokerClientError(str(code), str(message))

        result = response.get("result")
        if not isinstance(result, dict):
            raise BrokerClientError("invalid_response", "broker result is not an object")
        return result
