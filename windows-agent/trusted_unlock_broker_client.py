"""Minimal client for the local Trusted Unlock named pipe."""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

from trusted_unlock_broker import MAX_MESSAGE_BYTES, PIPE_NAME, PROTOCOL_VERSION


class BrokerClientError(Exception):
    """The broker could not be reached or rejected the request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


_RESPONSE_FIELDS = frozenset({"ok", "request_id", "result", "error"})
_ERROR_FIELDS = frozenset({"code", "message"})
_RESPONSE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_MAX_ERROR_TEXT_LENGTH = 256


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _invalid_response(message: str) -> BrokerClientError:
    return BrokerClientError("invalid_response", message)


def _decode_response(raw_response: bytes, request_id: str) -> dict[str, object]:
    """Decode one strict broker envelope before exposing its result to callers."""

    try:
        response = json.loads(
            raw_response.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise _invalid_response("broker response is invalid") from error

    if not isinstance(response, dict) or set(response) - _RESPONSE_FIELDS:
        raise _invalid_response("broker response has unsupported fields")
    if response.get("request_id") != request_id:
        raise _invalid_response("broker response does not match the request")

    ok = response.get("ok")
    if ok is True:
        if set(response) != {"ok", "request_id", "result"}:
            raise _invalid_response("successful broker response has invalid fields")
        result = response.get("result")
        if not isinstance(result, dict):
            raise _invalid_response("broker result is not an object")
        return result

    if ok is not False or set(response) != {"ok", "request_id", "error"}:
        raise _invalid_response("broker response envelope is invalid")
    error_data = response.get("error")
    if not isinstance(error_data, dict) or set(error_data) != _ERROR_FIELDS:
        raise _invalid_response("broker error is invalid")
    code = error_data.get("code")
    message = error_data.get("message")
    if (
        not isinstance(code, str)
        or _RESPONSE_CODE_PATTERN.fullmatch(code) is None
        or not isinstance(message, str)
        or not 1 <= len(message) <= _MAX_ERROR_TEXT_LENGTH
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in message)
    ):
        raise _invalid_response("broker error is invalid")
    raise BrokerClientError(code, message)


class WindowsNamedPipeBrokerClient:
    """Send bounded JSON requests to the local broker."""

    def __init__(self, *, pipe_name: str = PIPE_NAME, timeout_ms: int = 5000) -> None:
        if pipe_name != PIPE_NAME:
            raise ValueError("only the fixed local Pipa broker pipe is allowed")
        if timeout_ms < 1 or timeout_ms > 60_000:
            raise ValueError("timeout_ms must be between 1 and 60000")
        self._pipe_name = pipe_name
        self._timeout_ms = timeout_ms

    def request(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
        if not isinstance(command, str) or not command:
            raise ValueError("command must be a non-empty string")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        request_payload = {} if payload is None else payload
        request_id = secrets.token_hex(8)
        request = {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "command": command,
            "payload": request_payload,
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
        return _decode_response(raw_response, request_id)
