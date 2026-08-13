"""Strict JSON envelope over the opt-in secure session v2 record layer."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from secure_session import (
    MAX_RECORD_BYTES,
    RecordError,
    SecureSession,
)

SECURE_JSON_AAD = b"pipa/json/v2"
_FRAME_FIELDS = frozenset({"ciphertext", "protocol_version", "sequence", "session_id"})


class SecureJsonError(RecordError):
    """The encrypted JSON payload or its outer envelope is invalid."""


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SecureJsonError("JSON payload contains duplicate fields")
        result[key] = value
    return result


class SecureJsonChannel:
    """Serialize bounded JSON objects and protect them with a SecureSession."""

    def __init__(self, session: SecureSession) -> None:
        if not isinstance(session, SecureSession):
            raise TypeError("session must be SecureSession")
        self.session = session

    def seal_message(self, payload: Mapping[str, Any]) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            raise SecureJsonError("secure JSON payload must be an object")
        try:
            encoded = json.dumps(
                dict(payload),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as error:
            raise SecureJsonError("secure JSON payload is not valid finite JSON") from error
        if len(encoded) > MAX_RECORD_BYTES:
            raise SecureJsonError(f"secure JSON payload exceeds {MAX_RECORD_BYTES} bytes")
        return self.session.seal(encoded, additional_data=SECURE_JSON_AAD)

    def open_message(self, frame: Mapping[str, Any]) -> dict[str, object]:
        if not isinstance(frame, Mapping) or set(frame) != _FRAME_FIELDS:
            raise SecureJsonError("secure JSON frame has an invalid field set")
        try:
            encoded = self.session.open(dict(frame), additional_data=SECURE_JSON_AAD)
        except RecordError:
            raise
        try:
            payload = json.loads(encoded.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError, SecureJsonError) as error:
            raise SecureJsonError("decrypted payload is not valid JSON") from error
        if not isinstance(payload, dict):
            raise SecureJsonError("decrypted JSON payload must be an object")
        return payload

    def close(self) -> None:
        self.session.close()
