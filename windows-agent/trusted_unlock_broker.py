"""Local broker for the future Trusted Unlock flow.

The broker is deliberately conservative: it authenticates a paired device,
issues a one-use ticket, and exposes no operation that unlocks Windows.  The
transport is a Windows named pipe with an explicit ACL for the current user
and SYSTEM.  HTTP is intentionally not involved.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from typing import Any

from trusted_unlock_devices import DeviceStore, WindowsRegistryDeviceStore, verifier_from_store
from trusted_unlock_protocol import (
    AuthorizationVerifier,
    ChallengeMismatchError,
    ExpiredChallengeError,
    InvalidResponseError,
    ReplayDetectedError,
    SignedChallenge,
    TrustedUnlockError,
    UnknownChallengeError,
    UnknownDeviceError,
)
from trusted_unlock_ticket import (
    ExpiredTicketError,
    IssuedTicket,
    TicketError,
    TicketIssuer,
    TicketOperationError,
    TicketReplayError,
    UnknownTicketError,
)


BROKER_VERSION = "0.1.0"
PROTOCOL_VERSION = 1
PIPE_NAME = r"\\.\pipe\PipaTrustedUnlock"
MAX_MESSAGE_BYTES = 16 * 1024
UNLOCK_ENABLED = False

_REQUEST_ID_PATTERN = re.compile(r"^[^\x00-\x1f]{1,64}$")


class BrokerRequestError(Exception):
    """A request is malformed or asks for an unsupported operation."""


def _require_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _REQUEST_ID_PATTERN.fullmatch(value) is None:
        raise BrokerRequestError(f"{field_name} must be a printable string")
    return value


def _require_payload(request: dict[str, Any]) -> dict[str, Any]:
    payload = request.get("payload", {})
    if not isinstance(payload, dict):
        raise BrokerRequestError("payload must be an object")
    return payload


def _issued_ticket_dict(ticket: IssuedTicket) -> dict[str, object]:
    return {
        "token": ticket.token,
        "device_id": ticket.device_id,
        "operation": ticket.operation,
        "issued_at": ticket.issued_at,
        "expires_at": ticket.expires_at,
    }


def _error_code(error: Exception) -> str:
    mapping = {
        UnknownDeviceError: "unknown_device",
        UnknownChallengeError: "unknown_challenge",
        ChallengeMismatchError: "challenge_mismatch",
        ExpiredChallengeError: "expired_challenge",
        InvalidResponseError: "invalid_response",
        ReplayDetectedError: "replay_detected",
        UnknownTicketError: "unknown_ticket",
        ExpiredTicketError: "expired_ticket",
        TicketReplayError: "ticket_replay",
        TicketOperationError: "ticket_operation_mismatch",
    }
    for error_type, code in mapping.items():
        if isinstance(error, error_type):
            return code
    if isinstance(error, BrokerRequestError):
        return "invalid_request"
    if isinstance(error, (TrustedUnlockError, TicketError)):
        return "authorization_failed"
    return "internal_error"


class TrustedUnlockBroker:
    """Validate broker requests without ever performing a Windows unlock."""

    def __init__(
        self,
        verifier: AuthorizationVerifier,
        ticket_issuer: TicketIssuer | None = None,
    ) -> None:
        self._verifier = verifier
        self._ticket_issuer = ticket_issuer or TicketIssuer()

    @classmethod
    def from_store(cls, store: DeviceStore) -> "TrustedUnlockBroker":
        return cls(verifier_from_store(store))

    def handle_bytes(self, raw_request: bytes) -> bytes:
        if len(raw_request) > MAX_MESSAGE_BYTES:
            return self._encode_response(None, False, "invalid_request", "message too large")

        try:
            request = json.loads(raw_request.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._encode_response(None, False, "invalid_request", "invalid JSON")

        response = self.handle_request(request)
        return json.dumps(
            response,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def handle_request(self, request: Any) -> dict[str, object]:
        request_id = request.get("request_id") if isinstance(request, dict) else None
        if not isinstance(request_id, str) or _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
            request_id = None

        try:
            if not isinstance(request, dict):
                raise BrokerRequestError("request must be an object")
            request_id = _require_identifier(request.get("request_id"), "request_id")
            if request.get("version") != PROTOCOL_VERSION:
                raise BrokerRequestError("unsupported broker protocol version")

            command = _require_identifier(request.get("command"), "command")
            result = self._dispatch(command, _require_payload(request))
            return {"ok": True, "request_id": request_id, "result": result}
        except Exception as error:  # Convert expected failures into safe wire responses.
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": _error_code(error),
                    "message": str(error) if isinstance(error, (BrokerRequestError, TrustedUnlockError, TicketError)) else "request failed",
                },
            }

    def _dispatch(self, command: str, payload: dict[str, Any]) -> dict[str, object]:
        if command == "health":
            return {
                "broker_version": BROKER_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "unlock_enabled": UNLOCK_ENABLED,
                "pending_challenges": self._verifier.pending_count,
                "pending_tickets": self._ticket_issuer.pending_count,
            }

        if command == "challenge.create":
            device_id = _require_identifier(payload.get("device_id"), "device_id")
            ttl_seconds = payload.get("ttl_seconds", 30)
            if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
                raise BrokerRequestError("ttl_seconds must be an integer")
            challenge = self._verifier.create_challenge(device_id, ttl_seconds=ttl_seconds)
            return {"challenge": challenge.as_dict()}

        if command == "challenge.submit":
            response_data = payload.get("response")
            if not isinstance(response_data, dict):
                raise BrokerRequestError("response must be an object")
            try:
                response = SignedChallenge(**response_data)
            except (TypeError, ValueError) as error:
                raise BrokerRequestError("response has invalid fields") from error
            authorization = self._verifier.verify_response(response)
            ticket = self._ticket_issuer.issue(authorization)
            return {
                "ticket": _issued_ticket_dict(ticket),
                "unlock_enabled": UNLOCK_ENABLED,
            }

        if command == "ticket.consume":
            token = payload.get("token")
            if not isinstance(token, str) or not token:
                raise BrokerRequestError("token must be a non-empty string")
            ticket = self._ticket_issuer.consume(token)
            return {
                "consumed": True,
                "device_id": ticket.device_id,
                "operation": ticket.operation,
                "unlock_enabled": UNLOCK_ENABLED,
            }

        raise BrokerRequestError("unsupported broker command")

    @staticmethod
    def _encode_response(
        request_id: str | None,
        ok: bool,
        code: str,
        message: str,
    ) -> bytes:
        response = {
            "ok": ok,
            "request_id": request_id,
            "error": {"code": code, "message": message},
        }
        return json.dumps(response, separators=(",", ":")).encode("utf-8")


class WindowsNamedPipeBroker:
    """Serve one JSON message at a time over an ACL-protected named pipe."""

    def __init__(self, broker: TrustedUnlockBroker, *, pipe_name: str = PIPE_NAME) -> None:
        self._broker = broker
        self._pipe_name = pipe_name

    @staticmethod
    def _security_attributes():
        import pywintypes
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY,
        )
        try:
            user_sid = win32security.GetTokenInformation(
                token,
                win32security.TokenUser,
            )[0]
        finally:
            win32api.CloseHandle(token)

        system_sid = win32security.LookupAccountName(None, "SYSTEM")[0]
        dacl = win32security.ACL()
        rights = win32con.GENERIC_READ | win32con.GENERIC_WRITE
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, rights, user_sid)
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, rights, system_sid)

        descriptor = win32security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        # Keep the descriptor objects alive for the lifetime of the returned
        # SECURITY_ATTRIBUTES object; pywin32 stores native pointers in it.
        return attributes, descriptor, dacl

    def serve_forever(self) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsNamedPipeBroker requires Windows")

        import pywintypes
        import win32file
        import win32pipe
        from winerror import ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_PIPE_CONNECTED

        security_attributes, _descriptor, _dacl = self._security_attributes()
        while True:
            pipe = win32pipe.CreateNamedPipe(
                self._pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE
                | win32pipe.PIPE_READMODE_MESSAGE
                | win32pipe.PIPE_WAIT
                | getattr(win32pipe, "PIPE_REJECT_REMOTE_CLIENTS", 0),
                1,
                MAX_MESSAGE_BYTES,
                MAX_MESSAGE_BYTES,
                0,
                security_attributes,
            )
            try:
                try:
                    win32pipe.ConnectNamedPipe(pipe, None)
                except pywintypes.error as error:
                    if error.winerror != ERROR_PIPE_CONNECTED:
                        raise

                while True:
                    try:
                        _, raw_request = win32file.ReadFile(pipe, MAX_MESSAGE_BYTES + 1)
                    except pywintypes.error as error:
                        if error.winerror in (ERROR_BROKEN_PIPE, ERROR_NO_DATA):
                            break
                        raise

                    if not raw_request:
                        break
                    win32file.WriteFile(pipe, self._broker.handle_bytes(raw_request))
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(pipe)
                except pywintypes.error:
                    pass
                win32file.CloseHandle(pipe)


def main() -> int:
    try:
        store = WindowsRegistryDeviceStore()
        broker = TrustedUnlockBroker.from_store(store)
        print(f"Pipa Trusted Unlock broker {BROKER_VERSION}")
        print(f"Named Pipe: {PIPE_NAME}")
        print("Unlock enabled: FALSE")
        WindowsNamedPipeBroker(broker).serve_forever()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"ERROR: broker no iniciado: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
