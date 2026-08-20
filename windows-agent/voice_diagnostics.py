"""Short-lived, local-only diagnostics for the physical voice path."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence

from tools.text_policy import validate_bounded_text

VOICE_DIAGNOSTIC_TTL_SECONDS = 10 * 60
MAX_DIAGNOSTIC_TRANSCRIPT_BYTES = 1024
_NUMERIC_STT_FIELDS = frozenset(
    {
        "audio_duration_ms",
        "peak_dbfs",
        "rms_dbfs",
        "applied_gain_db",
        "clipped_percent",
        "segment_count",
        "speech_duration_ms",
        "average_log_probability",
        "no_speech_probability",
        "language_probability",
    }
)
_TEXT_STT_FIELDS = frozenset({"model", "device"})


def _bounded_transcript(value: str) -> tuple[str, bool]:
    validated = validate_bounded_text(value, "La transcripción", 4000).strip()
    encoded = validated.encode("utf-8")
    if len(encoded) <= MAX_DIAGNOSTIC_TRANSCRIPT_BYTES:
        return validated, False
    shortened = encoded[:MAX_DIAGNOSTIC_TRANSCRIPT_BYTES]
    while shortened:
        try:
            return shortened.decode("utf-8"), True
        except UnicodeDecodeError:
            shortened = shortened[:-1]
    return "", True


def _safe_stt_metadata(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    result: dict[str, object] = {}
    for key in _NUMERIC_STT_FIELDS:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        if isinstance(item, float) and not math.isfinite(item):
            continue
        result[key] = item
    for key in _TEXT_STT_FIELDS:
        item = value.get(key)
        if isinstance(item, str) and 0 < len(item) <= 32 and item.isascii():
            result[key] = item
    return result


def _classify_messages(messages: Sequence[Mapping[str, object]]) -> tuple[str, str | None, str | None]:
    tool_name = None
    error_code = None
    confirmation_required = False
    tool_result_success: bool | None = None
    for message in messages:
        message_type = message.get("type")
        if message_type in {"confirm_request", "tool_result"} and isinstance(message.get("tool_name"), str):
            tool_name = str(message["tool_name"])
        if message_type == "confirm_request":
            confirmation_required = True
        if message_type == "tool_result" and isinstance(message.get("success"), bool):
            tool_result_success = bool(message["success"])
        if message_type == "error" and isinstance(message.get("code"), str):
            error_code = str(message["code"])
    if error_code == "unsupported_text_intent":
        return "unrecognized", tool_name, error_code
    if error_code is not None:
        return "error", tool_name, error_code
    if tool_result_success is not None:
        return ("completed" if tool_result_success else "failed"), tool_name, None
    if confirmation_required:
        return "confirmation_required", tool_name, None
    if tool_name is not None:
        return "recognized", tool_name, None
    return "captured", None, None


class VoiceDiagnosticStore:
    """Keep one bounded transcript in memory and expire it automatically."""

    def __init__(
        self,
        *,
        ttl_seconds: float = VOICE_DIAGNOSTIC_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("voice diagnostic TTL is outside the safe range")
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._lock = threading.RLock()
        self._record: dict[str, object] | None = None

    def record(
        self,
        transcript: str,
        *,
        stt_metadata: Mapping[str, object] | None,
        messages: Sequence[Mapping[str, object]],
    ) -> None:
        bounded, truncated = _bounded_transcript(transcript)
        status, tool_name, error_code = _classify_messages(messages)
        record: dict[str, object] = {
            "recorded_at": self._clock(),
            "transcript": bounded,
            "transcript_truncated": truncated,
            "status": status,
            "recognized": status in {"recognized", "confirmation_required", "completed", "failed"},
            "stt": _safe_stt_metadata(stt_metadata),
        }
        if tool_name is not None:
            record["tool_name"] = tool_name
        if error_code is not None:
            record["error_code"] = error_code
        with self._lock:
            self._record = record

    def update_from_messages(self, messages: Sequence[Mapping[str, object]]) -> None:
        """Attach the result of a later physical confirmation to the capture."""

        status, tool_name, error_code = _classify_messages(messages)
        if status == "captured":
            return
        with self._lock:
            if self._record is None:
                return
            if self._clock() - float(self._record["recorded_at"]) > self.ttl_seconds:
                self._record = None
                return
            self._record["status"] = status
            self._record["recognized"] = bool(
                self._record.get("recognized")
                or status in {"recognized", "confirmation_required", "completed", "failed"}
            )
            if tool_name is not None:
                self._record["tool_name"] = tool_name
            if error_code is None:
                self._record.pop("error_code", None)
            else:
                self._record["error_code"] = error_code

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            record = None if self._record is None else dict(self._record)
        if record is None:
            return {"success": True, "available": False, "reason": "no_capture"}
        age_seconds = max(0.0, self._clock() - float(record.pop("recorded_at")))
        if age_seconds > self.ttl_seconds:
            with self._lock:
                self._record = None
            return {"success": True, "available": False, "reason": "expired"}
        record["success"] = True
        record["available"] = True
        record["age_ms"] = int(age_seconds * 1000)
        record["retention_seconds"] = int(self.ttl_seconds)
        return record
