"""Versioned, strict JSON messages for device-to-core communication."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_TEXT_LENGTH = 4000
MAX_TOOL_NAME_LENGTH = 80
MAX_ARGUMENTS_BYTES = 4096
MAX_CAPABILITIES = 16
TEXT_SOURCES = frozenset({"voice", "touch", "mobile", "debug", "unknown"})
AUDIO_STATES = frozenset({"disabled", "probe_only", "codec_ready", "listening", "draining", "error"})
_COMMON_FIELDS = frozenset({"protocol_version", "type"})
_MESSAGE_FIELDS = {
    "challenge_request": frozenset({"device_id"}),
    "hello": frozenset({"device_id", "challenge_id", "signature", "firmware_version", "capabilities"}),
    "device_hello": frozenset({"firmware_version", "capabilities"}),
    "catalog_request": frozenset(),
    "text_input": frozenset({"text", "source"}),
    "wake": frozenset(),
    "hold_start": frozenset(),
    "hold_end": frozenset(),
    "audio_end": frozenset(),
    "abort": frozenset(),
    "ping": frozenset({"request_id"}),
    "device_status": frozenset({"audio_state", "battery_percent", "wifi_rssi"}),
    "gesture": frozenset({"gesture"}),
    "tool_call": frozenset({"name", "arguments", "call_id"}),
    "confirm": frozenset({"confirmation_id", "accepted"}),
}


class ProtocolError(ValueError):
    """A message does not satisfy the Pipα wire contract."""


def _string(payload: Mapping[str, Any], name: str, *, maximum: int = 256) -> str:
    value = payload.get(name)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ProtocolError(f"{name} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _protocol_version(payload: Mapping[str, Any]) -> int:
    version = payload.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol_version: {version!r}")
    return version


def _optional_string(payload: Mapping[str, Any], name: str, *, maximum: int = 256) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    return _string(payload, name, maximum=maximum)


def _capabilities(payload: Mapping[str, Any]) -> list[str]:
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list) or len(capabilities) > MAX_CAPABILITIES:
        raise ProtocolError(f"capabilities must be a list of at most {MAX_CAPABILITIES} items")
    parsed_capabilities = []
    for capability in capabilities:
        if (
            not isinstance(capability, str)
            or not capability.strip()
            or len(capability) > 32
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in capability)
        ):
            raise ProtocolError("capabilities must contain non-empty strings of at most 32 characters")
        parsed_capabilities.append(capability.strip())
    if len(set(parsed_capabilities)) != len(parsed_capabilities):
        raise ProtocolError("capabilities must not contain duplicates")
    return parsed_capabilities


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
    allowed_fields = _MESSAGE_FIELDS.get(message_type)
    if allowed_fields is None:
        raise ProtocolError(f"unsupported message type: {message_type}")
    unknown_fields = set(payload) - _COMMON_FIELDS - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(str(name) for name in unknown_fields))
        raise ProtocolError(f"unexpected fields for {message_type}: {names}")

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
        firmware_version = _optional_string(payload, "firmware_version", maximum=32)
        if firmware_version is not None:
            fields["firmware_version"] = firmware_version
        fields["capabilities"] = _capabilities(payload)
    elif message_type == "device_hello":
        firmware_version = _optional_string(payload, "firmware_version", maximum=32)
        if firmware_version is not None:
            fields["firmware_version"] = firmware_version
        fields["capabilities"] = _capabilities(payload)
    elif message_type == "text_input":
        fields["text"] = _string(payload, "text", maximum=MAX_TEXT_LENGTH)
        source = payload.get("source", "unknown")
        if not isinstance(source, str) or source not in TEXT_SOURCES:
            raise ProtocolError("unsupported text source")
        fields["source"] = source
    elif message_type in {"catalog_request", "wake", "hold_start", "hold_end", "audio_end", "abort"}:
        pass
    elif message_type == "ping":
        request_id = _optional_string(payload, "request_id", maximum=64)
        if request_id is not None:
            fields["request_id"] = request_id
    elif message_type == "device_status":
        audio_state = payload.get("audio_state")
        if audio_state is not None and (not isinstance(audio_state, str) or audio_state not in AUDIO_STATES):
            raise ProtocolError("audio_state must be one of the known diagnostic states")
        battery_percent = payload.get("battery_percent")
        if battery_percent is not None and (
            not isinstance(battery_percent, int)
            or isinstance(battery_percent, bool)
            or not 0 <= battery_percent <= 100
        ):
            raise ProtocolError("battery_percent must be an integer between 0 and 100")
        wifi_rssi = payload.get("wifi_rssi")
        if wifi_rssi is not None and (
            not isinstance(wifi_rssi, int) or isinstance(wifi_rssi, bool) or not -127 <= wifi_rssi <= 0
        ):
            raise ProtocolError("wifi_rssi must be an integer between -127 and 0")
        fields["audio_state"] = audio_state
        fields["battery_percent"] = battery_percent
        fields["wifi_rssi"] = wifi_rssi
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
        try:
            encoded_arguments = json.dumps(
                arguments,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as error:
            raise ProtocolError("arguments must be finite, JSON-serializable data") from error
        if len(encoded_arguments) > MAX_ARGUMENTS_BYTES:
            raise ProtocolError(f"arguments must fit in {MAX_ARGUMENTS_BYTES} UTF-8 bytes")
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
    return ClientMessage(message_type, fields)


def server_message(message_type: str, **fields: Any) -> dict[str, Any]:
    if not isinstance(message_type, str) or not message_type.strip():
        raise ValueError("server message type is required")
    if "type" in fields or "protocol_version" in fields:
        raise ValueError("reserved server message fields cannot be overridden")
    return {"protocol_version": PROTOCOL_VERSION, "type": message_type, **fields}
