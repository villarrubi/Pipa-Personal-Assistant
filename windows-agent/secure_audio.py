"""Bounded encrypted audio chunks for the opt-in secure-session v2 layer.

This module is deliberately not connected to the v1 protocol, the resident
agent, or the firmware audio probe.  It defines the future binary payload
contract so a later microphone implementation cannot accidentally put samples
in JSON, logs, or an unauthenticated transport.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from secure_session import RecordError, SecureSession

AUDIO_PROTOCOL_VERSION = 2
AUDIO_AAD_PREFIX = b"pipa/audio/v2\x00"
AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
AUDIO_BITS_PER_SAMPLE = 16
AUDIO_BYTES_PER_SAMPLE = AUDIO_BITS_PER_SAMPLE // 8
MAX_AUDIO_CHUNK_BYTES = 4096
MAX_AUDIO_CHUNKS = 64
MAX_AUDIO_STREAM_BYTES = MAX_AUDIO_CHUNK_BYTES * MAX_AUDIO_CHUNKS
MAX_AUDIO_STREAM_DURATION_MS = (
    MAX_AUDIO_STREAM_BYTES * 1000 // (AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_BYTES_PER_SAMPLE)
)
MAX_AUDIO_STREAM_ID_LENGTH = 64
_STREAM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_RECORD_FIELDS = frozenset({"ciphertext", "protocol_version", "sequence", "session_id"})
_AUDIO_FIELDS = frozenset(
    {
        "audio_protocol_version",
        "bits_per_sample",
        "channels",
        "chunk_index",
        "final",
        "sample_rate",
        "stream_id",
    }
)
_FRAME_FIELDS = _RECORD_FIELDS | _AUDIO_FIELDS


class AudioFrameError(RecordError):
    """An encrypted audio frame violates the bounded audio contract."""


@dataclass(frozen=True)
class AudioStreamSummary:
    """Bounded metadata returned after an audio stream reaches its final frame."""

    stream_bytes: int
    stream_duration_ms: int


AudioChunkConsumer = Callable[[memoryview, bool], None]


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise AudioFrameError("audio metadata is not canonical JSON") from error


def _validate_stream_id(value: object) -> str:
    if not isinstance(value, str) or _STREAM_ID_PATTERN.fullmatch(value) is None:
        raise AudioFrameError("audio stream_id is invalid")
    return value


def _validate_chunk_index(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < MAX_AUDIO_CHUNKS:
        raise AudioFrameError("audio chunk_index is invalid")
    return value


def _validate_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, Mapping) or set(metadata) != _AUDIO_FIELDS:
        raise AudioFrameError("audio metadata has an invalid field set")

    if metadata["audio_protocol_version"] != AUDIO_PROTOCOL_VERSION:
        raise AudioFrameError("unsupported audio protocol version")
    stream_id = _validate_stream_id(metadata["stream_id"])
    chunk_index = _validate_chunk_index(metadata["chunk_index"])
    if not isinstance(metadata["final"], bool):
        raise AudioFrameError("audio final marker is invalid")
    if (
        metadata["sample_rate"] != AUDIO_SAMPLE_RATE
        or metadata["channels"] != AUDIO_CHANNELS
        or metadata["bits_per_sample"] != AUDIO_BITS_PER_SAMPLE
    ):
        raise AudioFrameError("unsupported audio sample format")
    return {
        "audio_protocol_version": AUDIO_PROTOCOL_VERSION,
        "bits_per_sample": AUDIO_BITS_PER_SAMPLE,
        "channels": AUDIO_CHANNELS,
        "chunk_index": chunk_index,
        "final": metadata["final"],
        "sample_rate": AUDIO_SAMPLE_RATE,
        "stream_id": stream_id,
    }


def _additional_data(metadata: Mapping[str, Any]) -> bytes:
    return AUDIO_AAD_PREFIX + _canonical(metadata)


def _validate_samples(samples: bytes) -> bytes:
    if not isinstance(samples, bytes):
        raise AudioFrameError("audio samples must be bytes")
    if not 0 < len(samples) <= MAX_AUDIO_CHUNK_BYTES or len(samples) % AUDIO_BYTES_PER_SAMPLE:
        raise AudioFrameError("audio chunk size is invalid")
    return samples


class SecureAudioSender:
    """Create sequential encrypted PCM chunks without storing a stream."""

    def __init__(self, session: SecureSession, stream_id: str) -> None:
        if not isinstance(session, SecureSession):
            raise TypeError("session must be SecureSession")
        self.session = session
        self.stream_id = _validate_stream_id(stream_id)
        self._next_chunk = 0
        self._stream_bytes = 0
        self._finished = False

    def seal_chunk(self, samples: bytes, *, final: bool) -> dict[str, object]:
        if self._finished:
            raise AudioFrameError("audio stream is already finished")
        if not isinstance(final, bool):
            raise AudioFrameError("audio final marker is invalid")
        if self._next_chunk >= MAX_AUDIO_CHUNKS:
            raise AudioFrameError("audio stream has too many chunks")
        samples = _validate_samples(samples)
        if self._stream_bytes + len(samples) > MAX_AUDIO_STREAM_BYTES:
            raise AudioFrameError("audio stream is too large")
        if self._next_chunk == MAX_AUDIO_CHUNKS - 1 and not final:
            raise AudioFrameError("audio stream must finish before its chunk limit")

        metadata = _validate_metadata(
            {
                "audio_protocol_version": AUDIO_PROTOCOL_VERSION,
                "bits_per_sample": AUDIO_BITS_PER_SAMPLE,
                "channels": AUDIO_CHANNELS,
                "chunk_index": self._next_chunk,
                "final": final,
                "sample_rate": AUDIO_SAMPLE_RATE,
                "stream_id": self.stream_id,
            }
        )
        frame = self.session.seal(samples, additional_data=_additional_data(metadata))
        frame.update(metadata)
        self._next_chunk += 1
        self._stream_bytes += len(samples)
        self._finished = final
        return frame

    def cancel(self) -> None:
        """Discard stream state; the secure control session remains usable."""

        self._finished = True
        self._next_chunk = 0
        self._stream_bytes = 0


class SecureAudioReceiver:
    """Validate and decrypt one ordered audio stream from a secure session."""

    def __init__(self, session: SecureSession) -> None:
        if not isinstance(session, SecureSession):
            raise TypeError("session must be SecureSession")
        self.session = session
        self._stream_id: str | None = None
        self._next_chunk = 0
        self._stream_bytes = 0
        self._finished = False

    @property
    def complete(self) -> bool:
        return self._finished

    @property
    def stream_bytes(self) -> int:
        return self._stream_bytes

    @property
    def stream_duration_ms(self) -> int:
        return self._stream_bytes * 1000 // (AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_BYTES_PER_SAMPLE)

    def open_chunk(self, frame: Mapping[str, object]) -> bytes:
        """Return one plaintext chunk; invalid input closes the secure session."""

        try:
            if not isinstance(frame, Mapping) or set(frame) != _FRAME_FIELDS:
                raise AudioFrameError("audio frame has an invalid field set")
            metadata = _validate_metadata({key: frame[key] for key in _AUDIO_FIELDS})
            if self._finished:
                raise AudioFrameError("audio stream is already finished")
            if self._stream_id is None:
                if metadata["chunk_index"] != 0:
                    raise AudioFrameError("audio stream does not start at chunk zero")
                self._stream_id = metadata["stream_id"]
            elif metadata["stream_id"] != self._stream_id:
                raise AudioFrameError("audio stream_id changed during capture")
            if metadata["chunk_index"] != self._next_chunk:
                raise AudioFrameError("audio chunks are out of order")

            plaintext = self.session.open(dict(frame), additional_data=_additional_data(metadata))
            plaintext = _validate_samples(plaintext)
            if self._stream_bytes + len(plaintext) > MAX_AUDIO_STREAM_BYTES:
                raise AudioFrameError("audio stream is too large")

            self._next_chunk += 1
            self._stream_bytes += len(plaintext)
            self._finished = metadata["final"]
            return plaintext
        except (AudioFrameError, RecordError) as error:
            self._discard_state()
            self.session.close()
            if isinstance(error, AudioFrameError):
                raise
            raise AudioFrameError("audio frame authentication failed") from error

    def cancel(self) -> None:
        """Discard all stream bookkeeping while keeping control session alive."""

        self._discard_state()

    def close(self) -> None:
        self._discard_state()
        self.session.close()

    def _discard_state(self) -> None:
        self._stream_id = None
        self._next_chunk = 0
        self._stream_bytes = 0
        self._finished = False


class SecureAudioConsumer:
    """Deliver authenticated PCM chunks to a future local transcriber.

    The consumer never accumulates a recording. Each decrypted chunk is copied
    into a short-lived mutable buffer, exposed as a memoryview for the
    callback, and invalidated and zeroed immediately afterwards. A callback
    failure closes the secure session so a partially consumed stream cannot be
    reused accidentally.
    """

    def __init__(self, receiver: SecureAudioReceiver, on_chunk: AudioChunkConsumer) -> None:
        if not isinstance(receiver, SecureAudioReceiver):
            raise TypeError("receiver must be SecureAudioReceiver")
        if not callable(on_chunk):
            raise TypeError("on_chunk must be callable")
        self.receiver = receiver
        self._on_chunk: AudioChunkConsumer | None = on_chunk
        self._closed = False
        self._finished = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def complete(self) -> bool:
        return self._finished

    @property
    def stream_bytes(self) -> int:
        return self.receiver.stream_bytes

    @property
    def stream_duration_ms(self) -> int:
        return self.receiver.stream_duration_ms

    def consume_frame(self, frame: Mapping[str, object]) -> bool:
        """Decrypt and deliver one frame; return whether it was the final one."""

        if self._closed:
            raise AudioFrameError("audio consumer is closed")
        if self._finished:
            self.close()
            raise AudioFrameError("audio stream is already finished")
        try:
            samples = self.receiver.open_chunk(frame)
        except AudioFrameError:
            self._closed = True
            self._on_chunk = None
            raise

        buffer = bytearray(samples)
        del samples
        view = memoryview(buffer)
        final = self.receiver.complete
        try:
            callback = self._on_chunk
            if callback is None:
                raise AudioFrameError("audio consumer has no callback")
            callback(view, final)
        except AudioFrameError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise AudioFrameError("audio consumer failed") from error
        finally:
            view.release()
            buffer[:] = b"\x00" * len(buffer)

        self._finished = final
        return final

    def finalize(self) -> AudioStreamSummary:
        """Return only bounded counters after a final frame was consumed."""

        if self._closed:
            raise AudioFrameError("audio consumer is closed")
        if not self._finished or not self.receiver.complete:
            self.close()
            raise AudioFrameError("audio stream ended before its final frame")
        return AudioStreamSummary(self.stream_bytes, self.stream_duration_ms)

    def cancel(self) -> None:
        """Discard the current stream while retaining the control session."""

        if self._closed:
            return
        self.receiver.cancel()
        self._finished = False

    def close(self) -> None:
        """Close the secure session and drop the callback reference."""

        if self._closed:
            return
        self.receiver.close()
        self._closed = True
        self._finished = False
        self._on_chunk = None
