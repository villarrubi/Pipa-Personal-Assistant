"""Bounded encrypted audio chunks for the opt-in secure-session v2 layer.

This module is never connected to v1. The resident V2 gateway uses it as the
only binary payload route so microphone samples cannot enter ordinary JSON,
logs, or an unauthenticated transport.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from secure_session import RecordError, SecureSession
from tools.text_policy import validate_bounded_text

AUDIO_PROTOCOL_VERSION = 2
AUDIO_AAD_PREFIX = b"pipa/audio/v2\x00"
AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
AUDIO_BITS_PER_SAMPLE = 16
AUDIO_BYTES_PER_SAMPLE = AUDIO_BITS_PER_SAMPLE // 8
MAX_AUDIO_CHUNK_BYTES = 4096
MAX_AUDIO_CHUNKS = 256
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


def is_secure_audio_frame(value: object) -> bool:
    """Identify the exact outer envelope before selecting the audio decoder."""

    return isinstance(value, Mapping) and set(value) == _FRAME_FIELDS


class AudioFrameError(RecordError):
    """An encrypted audio frame violates the bounded audio contract."""


@dataclass(frozen=True)
class AudioStreamSummary:
    """Bounded metadata returned after an audio stream reaches its final frame."""

    stream_bytes: int
    stream_duration_ms: int


AudioChunkConsumer = Callable[[memoryview, bool], None]
AudioTranscriptProvider = Callable[[memoryview, bool], object]
AudioTranscriptReset = Callable[[], None]
AudioTranscriptDispatcher = Callable[[str], object]


class AudioCaptureState(StrEnum):
    """Policy state for the local audio capture route."""

    DISABLED = "disabled"
    CODEC_READY = "codec_ready"
    LISTENING = "listening"
    DRAINING = "draining"
    ERROR = "error"


class AudioCaptureGate:
    """Require physical readiness, consent and a secure route before capture."""

    def __init__(self) -> None:
        self._state = AudioCaptureState.DISABLED

    @property
    def state(self) -> AudioCaptureState:
        return self._state

    @property
    def can_capture(self) -> bool:
        return self._state is AudioCaptureState.LISTENING

    @property
    def can_advertise_audio(self) -> bool:
        return self._state is AudioCaptureState.CODEC_READY

    def mark_codec_ready(self, codec_initialized: bool) -> bool:
        """Enter the stable ready state only after bounded physical setup."""

        if self._state not in {AudioCaptureState.DISABLED, AudioCaptureState.ERROR}:
            return False
        if not codec_initialized:
            self._state = AudioCaptureState.ERROR
            return False
        self._state = AudioCaptureState.CODEC_READY
        return True

    def begin_listening(
        self,
        *,
        display_ready: bool,
        consented: bool,
        secure_transport_ready: bool,
    ) -> bool:
        """Open capture only when all independent policy gates are true."""

        if (
            self._state is not AudioCaptureState.CODEC_READY
            or not display_ready
            or not consented
            or not secure_transport_ready
        ):
            return False
        self._state = AudioCaptureState.LISTENING
        return True

    def begin_draining(self) -> bool:
        if self._state is not AudioCaptureState.LISTENING:
            return False
        self._state = AudioCaptureState.DRAINING
        return True

    def finish_draining(self) -> bool:
        if self._state is not AudioCaptureState.DRAINING:
            return False
        self._state = AudioCaptureState.CODEC_READY
        return True

    def fail(self) -> None:
        """Disable capture after any transport, buffer or callback failure."""

        self._state = AudioCaptureState.ERROR


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
    if chunk_index == MAX_AUDIO_CHUNKS - 1 and not metadata["final"]:
        raise AudioFrameError("audio stream must finish before its chunk limit")
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


def _validate_decrypted_samples(samples: bytearray) -> bytearray:
    """Validate plaintext without converting it back to an immutable bytes object."""

    if not isinstance(samples, bytearray):
        raise AudioFrameError("decrypted audio samples have an invalid buffer type")
    if not 0 < len(samples) <= MAX_AUDIO_CHUNK_BYTES or len(samples) % AUDIO_BYTES_PER_SAMPLE:
        raise AudioFrameError("audio chunk size is invalid")
    return samples


def _zero_buffer(buffer: bytearray) -> None:
    """Best-effort zeroization for the mutable buffers owned by this module."""

    if buffer:
        buffer[:] = b"\x00" * len(buffer)


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

    def open_chunk(self, frame: Mapping[str, object]) -> bytearray:
        """Return mutable plaintext; callers must zero it after consuming it."""

        plaintext = bytearray()

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

            decrypted = self.session.open(dict(frame), additional_data=_additional_data(metadata))
            # Convert once at the cryptographic boundary.  The immutable
            # object returned by the crypto backend is released immediately;
            # all buffers owned by this audio layer are mutable from here on.
            plaintext = bytearray(decrypted)
            del decrypted
            plaintext = _validate_decrypted_samples(plaintext)
            if self._stream_bytes + len(plaintext) > MAX_AUDIO_STREAM_BYTES:
                raise AudioFrameError("audio stream is too large")

            self._next_chunk += 1
            self._stream_bytes += len(plaintext)
            self._finished = metadata["final"]
            return plaintext
        except (AudioFrameError, RecordError) as error:
            _zero_buffer(plaintext)
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
    """Deliver authenticated PCM chunks to a local transcriber.

    The consumer never accumulates a recording. Each decrypted chunk is copied
    into a short-lived mutable buffer, exposed as a memoryview for the
    callback, and invalidated and zeroed immediately afterwards. A callback
    failure closes the secure session so a partially consumed stream cannot be
    reused accidentally.
    """

    def __init__(
        self,
        receiver: SecureAudioReceiver,
        on_chunk: AudioChunkConsumer,
        gate: AudioCaptureGate,
    ) -> None:
        if not isinstance(receiver, SecureAudioReceiver):
            raise TypeError("receiver must be SecureAudioReceiver")
        if not callable(on_chunk):
            raise TypeError("on_chunk must be callable")
        if not isinstance(gate, AudioCaptureGate):
            raise TypeError("gate must be AudioCaptureGate")
        self.receiver = receiver
        self.gate = gate
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

    def begin_capture(
        self,
        *,
        display_ready: bool,
        consented: bool,
        secure_transport_ready: bool,
    ) -> None:
        """Open this stream only after the visible consent policy succeeds."""

        if self._closed or not self.gate.begin_listening(
            display_ready=display_ready,
            consented=consented,
            secure_transport_ready=secure_transport_ready,
        ):
            raise AudioFrameError("audio capture policy is not ready")

    def consume_frame(self, frame: Mapping[str, object]) -> bool:
        """Decrypt and deliver one frame; return whether it was the final one."""

        if self._closed:
            raise AudioFrameError("audio consumer is closed")
        if self._finished:
            self.close()
            raise AudioFrameError("audio stream is already finished")
        if not self.gate.can_capture:
            self.close()
            raise AudioFrameError("audio capture policy is not active")
        try:
            samples = self.receiver.open_chunk(frame)
        except AudioFrameError:
            self.gate.fail()
            self._closed = True
            self._on_chunk = None
            raise

        buffer = samples
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
            _zero_buffer(buffer)

        self._finished = final
        return final

    def finalize(self) -> AudioStreamSummary:
        """Return only bounded counters after a final frame was consumed."""

        if self._closed or not self._finished or not self.receiver.complete:
            self.close()
            raise AudioFrameError("audio stream ended before its final frame")
        if not self.gate.begin_draining() or not self.gate.finish_draining():
            self.close()
            raise AudioFrameError("audio capture policy cannot drain")
        return AudioStreamSummary(self.stream_bytes, self.stream_duration_ms)

    def cancel(self) -> None:
        """Discard the current stream while retaining the control session."""

        if self._closed:
            return
        self.receiver.cancel()
        if self.gate.state is AudioCaptureState.LISTENING:
            if not self.gate.begin_draining() or not self.gate.finish_draining():
                self.gate.fail()
        self._finished = False

    def close(self, *, close_session: bool = True) -> None:
        """Drop stream state and optionally close the shared control session."""

        if self._closed:
            return
        if close_session:
            self.receiver.close()
            self.gate.fail()
        else:
            self.receiver.cancel()
        self._closed = True
        self._finished = False
        self._on_chunk = None


class SecureAudioTranscriber:
    """Adapt ephemeral authenticated PCM chunks to a bounded transcript.

    The provider is deliberately injected: this class does not select an STT
    engine, open a microphone, persist samples, or make network requests. A
    local provider receives each short-lived ``memoryview`` and may
    return a transcript only for the final chunk. The transcript is validated
    before it can be handed to the command parser.
    """

    def __init__(
        self,
        receiver: SecureAudioReceiver,
        provider: AudioTranscriptProvider,
        gate: AudioCaptureGate,
        *,
        reset_provider: AudioTranscriptReset | None = None,
    ) -> None:
        if not isinstance(receiver, SecureAudioReceiver):
            raise TypeError("receiver must be SecureAudioReceiver")
        if not callable(provider):
            raise TypeError("provider must be callable")
        if not isinstance(gate, AudioCaptureGate):
            raise TypeError("gate must be AudioCaptureGate")
        if reset_provider is not None and not callable(reset_provider):
            raise TypeError("reset_provider must be callable")
        self._transcript: str | None = None
        self._provider: AudioTranscriptProvider | None = provider
        self._reset_provider: AudioTranscriptReset | None = reset_provider
        self._provider_closed = False
        self._finalized = False
        self._consumer = SecureAudioConsumer(receiver, self._consume_chunk, gate)

    @property
    def consumer(self) -> SecureAudioConsumer:
        """Expose only the bounded consumer lifecycle to integration code."""

        return self._consumer

    @property
    def transcript(self) -> str | None:
        """Return the validated final transcript, if one was produced."""

        return self._transcript if self._finalized else None

    @property
    def closed(self) -> bool:
        return self._provider_closed or self._consumer.closed

    def begin_capture(
        self,
        *,
        display_ready: bool,
        consented: bool,
        secure_transport_ready: bool,
    ) -> None:
        self._consumer.begin_capture(
            display_ready=display_ready,
            consented=consented,
            secure_transport_ready=secure_transport_ready,
        )

    def consume_frame(self, frame: Mapping[str, object]) -> bool:
        if self.closed:
            raise AudioFrameError("audio transcriber is closed")
        return self._consumer.consume_frame(frame)

    def finalize(self) -> AudioStreamSummary:
        summary = self._consumer.finalize()
        if self._transcript is None:
            self.close()
            raise AudioFrameError("audio provider returned no final transcript")
        self._finalized = True
        return summary

    def cancel(self) -> None:
        if self.closed:
            return
        try:
            self._consumer.cancel()
            self._reset_provider_state()
        except AudioFrameError:
            self.close()
            raise
        self._transcript = None
        self._finalized = False

    def close(self, *, close_session: bool = True) -> None:
        if self._provider_closed:
            return
        reset_provider = self._reset_provider
        self._provider_closed = True
        self._provider = None
        self._reset_provider = None
        self._transcript = None
        self._finalized = False
        try:
            if reset_provider is not None:
                reset_provider()
        except Exception:  # nosec B110
            # The provider is no longer reusable even if its own cleanup
            # failed. Drop every reference and close the authenticated audio
            # session rather than attempting a new stream with stale state.
            pass
        finally:
            self._consumer.close(close_session=close_session)

    def _reset_provider_state(self) -> None:
        reset_provider = self._reset_provider
        if reset_provider is None:
            return
        try:
            reset_provider()
        except Exception as error:
            raise AudioFrameError("audio provider reset failed") from error

    def _consume_chunk(self, view: memoryview, final: bool) -> None:
        if self._transcript is not None:
            raise AudioFrameError("audio provider returned more than one transcript")
        provider = self._provider
        if provider is None:
            raise AudioFrameError("audio provider is unavailable")
        result = provider(view, final)
        if not final:
            if result is not None:
                raise AudioFrameError("audio provider returned a partial transcript")
            return
        if result is None:
            return
        try:
            self._transcript = validate_bounded_text(result, "La transcripción", 4000).strip()
        except ValueError as error:
            raise AudioFrameError("audio provider returned an invalid transcript") from error


class SecureAudioCommandBridge:
    """Dispatch one finalized transcript and then destroy the audio session.

    The bridge is the narrow seam between the secure audio lifecycle and the
    Core. It never exposes PCM to the dispatcher, never dispatches partial
    results and closes the transcriber after a successful or failed dispatch.
    A cancelled capture may be started again through the same bridge, but a
    finalized stream can never be dispatched twice.
    """

    def __init__(
        self,
        transcriber: SecureAudioTranscriber,
        dispatch: AudioTranscriptDispatcher,
    ) -> None:
        if not isinstance(transcriber, SecureAudioTranscriber):
            raise TypeError("transcriber must be SecureAudioTranscriber")
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        self._transcriber: SecureAudioTranscriber | None = transcriber
        self._dispatch: AudioTranscriptDispatcher | None = dispatch
        self._dispatched = False

    @property
    def closed(self) -> bool:
        return self._transcriber is None or self._transcriber.closed

    def begin_capture(
        self,
        *,
        display_ready: bool,
        consented: bool,
        secure_transport_ready: bool,
    ) -> None:
        transcriber = self._require_transcriber()
        transcriber.begin_capture(
            display_ready=display_ready,
            consented=consented,
            secure_transport_ready=secure_transport_ready,
        )

    def consume_frame(self, frame: Mapping[str, object]) -> bool:
        return self._require_transcriber().consume_frame(frame)

    def finalize(self) -> tuple[AudioStreamSummary, object]:
        """Finalize audio, dispatch its text once and return bounded metadata."""

        if self._dispatched:
            raise AudioFrameError("audio transcript was already dispatched")
        transcriber = self._require_transcriber()
        try:
            summary = transcriber.finalize()
        except AudioFrameError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise AudioFrameError("audio transcript finalization failed") from error
        transcript = transcriber.transcript
        dispatch = self._dispatch
        if transcript is None or dispatch is None:
            self.close()
            raise AudioFrameError("audio transcript dispatch is unavailable")
        try:
            result = dispatch(transcript)
        except Exception as error:
            self.close()
            raise AudioFrameError("audio transcript dispatch failed") from error
        self._dispatched = True
        # A successful command has erased the provider and stream state, but
        # the encrypted control session must remain alive so its result can be
        # returned to the device. Authentication failures still use the
        # default close_session=True fail-closed path.
        self.close(close_session=False)
        return summary, result

    def cancel(self) -> None:
        transcriber = self._transcriber
        if transcriber is None:
            return
        transcriber.cancel()
        self._dispatched = False

    def close(self, *, close_session: bool = True) -> None:
        transcriber = self._transcriber
        self._transcriber = None
        self._dispatch = None
        if transcriber is not None:
            transcriber.close(close_session=close_session)

    def _require_transcriber(self) -> SecureAudioTranscriber:
        transcriber = self._transcriber
        if transcriber is None or transcriber.closed:
            self.close()
            raise AudioFrameError("audio command bridge is closed")
        return transcriber
