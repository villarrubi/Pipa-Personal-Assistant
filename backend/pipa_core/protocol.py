"""Versioned, strict JSON messages for device-to-core communication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PROTOCOL_VERSION = 1
MAX_TEXT_LENGTH = 4000
MAX_TOOL_NAME_LENGTH = 80


class ProtocolError(ValueError):
    """A message does not satisfy the Pipα wire contract."""


def _string(payload: Mapping[str, Any], name: str, *, maximum: int = 256) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProtocolError(f"{name} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _protocol_version(payload: Mapping[str, Any]) -> int:
    version = payload.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol_version: {version!r}")
    return version


@dataclass(frozen=True)
class ClientMessage:
    type: str
    fields: dict[str, Any]

    @property
    def protocol_version(self) -> int:
        return int(self.fields["protocol_version"])


def parse_client_message(payload: Mapping[str, Any]) -> ClientMessage:
    if not isinstance(payload, Mapping):
        raise ProtocolError("message must be a JSON object")

    message_type = payload.get("type")
    if not isinstance(message_type, str):
        raise ProtocolError("message type is required")

    version = _protocol_version(payload)
    fields: dict[str, Any] = {"protocol_version": version}

    if message_type == "challenge_request":
        fields["device_id"] = _string(payload, "device_id", maximum=64)
    elif message_type == "hello":
        fields.update(
            device_id=_string(payload, "device_id", maximum=64),
            challenge_id=_string(payload, "challenge_id", maximum=128),
            signature=_string(payload, "signature", maximum=256),
        )
    elif message_type == "text_input":
        fields["text"] = _string(payload, "text", maximum=MAX_TEXT_LENGTH)
    elif message_type in {"wake", "hold_start", "hold_end", "audio_end", "abort"}:
        pass
    elif message_type == "gesture":
        gesture = _string(payload, "gesture", maximum=32)
        if gesture not in {"tap", "double_tap", "swipe_left", "swipe_right"}:
            raise ProtocolError("unsupported gesture")
        fields["gesture"] = gesture
    elif message_type == "tool_call":
        fields["name"] = _string(payload, "name", maximum=MAX_TOOL_NAME_LENGTH)
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise ProtocolError("arguments must be a JSON object")
        fields["arguments"] = dict(arguments)
        call_id = payload.get("call_id")
        if call_id is not None:
            fields["call_id"] = _string(payload, "call_id", maximum=128)
    elif message_type == "confirm":
        fields["confirmation_id"] = _string(payload, "confirmation_id", maximum=128)
        accepted = payload.get("accepted")
        if not isinstance(accepted, bool):
            raise ProtocolError("accepted must be boolean")
        fields["accepted"] = accepted
    else:
        raise ProtocolError(f"unsupported message type: {message_type}")

    return ClientMessage(message_type, fields)


def server_message(message_type: str, **fields: Any) -> dict[str, Any]:
    if not isinstance(message_type, str) or not message_type.strip():
        raise ValueError("server message type is required")
    return {"protocol_version": PROTOCOL_VERSION, "type": message_type, **fields}
