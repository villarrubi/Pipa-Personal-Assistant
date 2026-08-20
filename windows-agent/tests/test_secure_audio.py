import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secure_audio import (  # noqa: E402
    MAX_AUDIO_CHUNK_BYTES,
    MAX_AUDIO_CHUNKS,
    AudioCaptureGate,
    AudioCaptureState,
    AudioFrameError,
    SecureAudioCommandBridge,
    SecureAudioConsumer,
    SecureAudioReceiver,
    SecureAudioSender,
    SecureAudioTranscriber,
)
from secure_session import ClosedSessionError, secure_session_from_shared_secret  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "mobile-ios" / "Tests" / "Fixtures" / "secure_audio_v2.json"


class SecureAudioTests(unittest.TestCase):
    @staticmethod
    def _session(role: str):
        return secure_session_from_shared_secret(
            "audio-vector",
            bytes(range(1, 33)),
            bytes(range(32, 64)),
            role=role,
        )

    @staticmethod
    def _listening_gate() -> AudioCaptureGate:
        gate = AudioCaptureGate()
        assert gate.mark_codec_ready(True)
        assert gate.begin_listening(
            display_ready=True,
            consented=True,
            secure_transport_ready=True,
        )
        return gate

    def test_capture_gate_requires_readiness_consent_and_visible_indicator(self):
        gate = AudioCaptureGate()

        self.assertEqual(gate.state, AudioCaptureState.DISABLED)
        self.assertFalse(gate.can_advertise_audio)
        self.assertFalse(
            gate.begin_listening(display_ready=True, consented=True, secure_transport_ready=True)
        )
        self.assertFalse(gate.mark_codec_ready(False))
        self.assertEqual(gate.state, AudioCaptureState.ERROR)
        self.assertTrue(gate.mark_codec_ready(True))
        self.assertFalse(
            gate.begin_listening(display_ready=False, consented=True, secure_transport_ready=True)
        )
        self.assertFalse(
            gate.begin_listening(display_ready=True, consented=False, secure_transport_ready=True)
        )
        self.assertFalse(
            gate.begin_listening(display_ready=True, consented=True, secure_transport_ready=False)
        )
        self.assertTrue(gate.begin_listening(display_ready=True, consented=True, secure_transport_ready=True))
        self.assertTrue(gate.begin_draining())
        self.assertTrue(gate.finish_draining())
        self.assertTrue(gate.can_advertise_audio)

    def test_consumer_rejects_audio_before_explicit_capture_consent(self):
        sender = SecureAudioSender(self._session("client"), "stream-policy")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=True)
        receiver = SecureAudioReceiver(self._session("server"))
        gate = AudioCaptureGate()
        self.assertTrue(gate.mark_codec_ready(True))
        consumer = SecureAudioConsumer(receiver, lambda _view, _final: None, gate)

        with self.assertRaises(AudioFrameError):
            consumer.consume_frame(frame)

        self.assertTrue(consumer.closed)
        self.assertEqual(gate.state, AudioCaptureState.ERROR)

    def test_cross_language_fixture_contains_only_encrypted_audio(self):
        vector = json.loads(FIXTURE.read_text(encoding="utf-8"))
        receiver = SecureAudioReceiver(self._session("server"))

        samples = receiver.open_chunk(vector["frame"])

        self.assertEqual(samples, bytes(range(32)))
        self.assertTrue(receiver.complete)
        self.assertEqual(receiver.stream_bytes, 32)
        self.assertEqual(receiver.stream_duration_ms, 1)
        self.assertNotIn("samples", vector["frame"])
        self.assertNotIn(vector["samples"], str(vector["frame"]))

    def test_sender_and_receiver_enforce_order_and_final_marker(self):
        sender = SecureAudioSender(self._session("client"), "stream-one")
        receiver = SecureAudioReceiver(self._session("server"))

        first = sender.seal_chunk(b"\x01\x02" * 100, final=False)
        second = sender.seal_chunk(b"\x03\x04" * 100, final=True)

        self.assertEqual(receiver.open_chunk(first), b"\x01\x02" * 100)
        self.assertFalse(receiver.complete)
        self.assertEqual(receiver.open_chunk(second), b"\x03\x04" * 100)
        self.assertTrue(receiver.complete)
        with self.assertRaises(AudioFrameError):
            receiver.open_chunk(second)

    def test_reordered_frame_closes_the_secure_session(self):
        sender = SecureAudioSender(self._session("client"), "stream-two")
        first = sender.seal_chunk(b"\x00\x01" * 4, final=False)
        second = sender.seal_chunk(b"\x02\x03" * 4, final=True)
        receiver = SecureAudioReceiver(self._session("server"))

        with self.assertRaises(AudioFrameError):
            receiver.open_chunk(second)
        with self.assertRaises(AudioFrameError):
            receiver.open_chunk(first)

    def test_metadata_tampering_is_authenticated_and_closes_session(self):
        sender = SecureAudioSender(self._session("client"), "stream-three")
        frame = sender.seal_chunk(b"\x00\x01" * 4, final=True)
        tampered = dict(frame)
        tampered["final"] = False
        receiver = SecureAudioReceiver(self._session("server"))

        with self.assertRaises(AudioFrameError):
            receiver.open_chunk(tampered)
        with self.assertRaises(AudioFrameError):
            receiver.open_chunk(frame)

    def test_chunk_and_stream_limits_are_bounded(self):
        sender = SecureAudioSender(self._session("client"), "stream-four")
        with self.assertRaises(AudioFrameError):
            sender.seal_chunk(b"x" * (MAX_AUDIO_CHUNK_BYTES + 1), final=True)

        for _index in range(MAX_AUDIO_CHUNKS - 1):
            sender.seal_chunk(b"\x00\x00", final=False)
        with self.assertRaises(AudioFrameError):
            sender.seal_chunk(b"\x00\x00", final=False)

    def test_receiver_rejects_a_nonfinal_last_chunk_and_closes_session(self):
        sender = SecureAudioSender(self._session("client"), "stream-last")
        for _index in range(MAX_AUDIO_CHUNKS - 1):
            sender.seal_chunk(b"\x00\x00", final=False)
        frame = sender.seal_chunk(b"\x01\x02", final=True)
        tampered = dict(frame)
        tampered["final"] = False
        receiver = SecureAudioReceiver(self._session("server"))

        with self.assertRaises(AudioFrameError):
            receiver.open_chunk(tampered)
        with self.assertRaises(ClosedSessionError):
            receiver.session.seal(b"\x00\x00")

    def test_cancel_discards_stream_state_without_logging_or_reusing_samples(self):
        sender = SecureAudioSender(self._session("client"), "stream-five")
        sender.seal_chunk(b"\x01\x02" * 8, final=False)
        sender.cancel()
        with self.assertRaises(AudioFrameError):
            sender.seal_chunk(b"\x03\x04", final=True)

    def test_consumer_delivers_ephemeral_chunks_and_returns_bounded_summary(self):
        sender = SecureAudioSender(self._session("client"), "stream-consumer")
        first = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        second = sender.seal_chunk(b"\x03\x04" * 4, final=True)
        receiver = SecureAudioReceiver(self._session("server"))
        received: list[bytes] = []
        retained_views: list[memoryview] = []

        def consume(view: memoryview, final: bool) -> None:
            received.append(bytes(view))
            retained_views.append(view)
            self.assertEqual(final, len(received) == 2)

        gate = self._listening_gate()
        consumer = SecureAudioConsumer(receiver, consume, gate)

        self.assertFalse(consumer.consume_frame(first))
        self.assertTrue(consumer.consume_frame(second))
        summary = consumer.finalize()

        self.assertEqual(received, [b"\x01\x02" * 4, b"\x03\x04" * 4])
        self.assertEqual(summary.stream_bytes, 16)
        self.assertEqual(summary.stream_duration_ms, 0)
        self.assertTrue(consumer.complete)
        self.assertEqual(gate.state, AudioCaptureState.CODEC_READY)
        with self.assertRaises(ValueError):
            len(retained_views[0])

    def test_receiver_exposes_plaintext_as_a_mutable_buffer(self):
        sender = SecureAudioSender(self._session("client"), "stream-mutable")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=True)
        receiver = SecureAudioReceiver(self._session("server"))

        plaintext = receiver.open_chunk(frame)

        self.assertIsInstance(plaintext, bytearray)
        self.assertEqual(plaintext, b"\x01\x02" * 4)
        plaintext[:] = b"\x00" * len(plaintext)
        self.assertEqual(plaintext, b"\x00" * 8)

    def test_consumer_callback_failure_closes_session_without_retrying(self):
        sender = SecureAudioSender(self._session("client"), "stream-failure")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=True)
        receiver = SecureAudioReceiver(self._session("server"))

        def fail(_view: memoryview, _final: bool) -> None:
            raise RuntimeError("private transcriber detail")

        consumer = SecureAudioConsumer(receiver, fail, self._listening_gate())
        with self.assertRaises(AudioFrameError):
            consumer.consume_frame(frame)
        self.assertTrue(consumer.closed)
        self.assertEqual(consumer.gate.state, AudioCaptureState.ERROR)
        with self.assertRaises(ClosedSessionError):
            receiver.session.seal(b"\x00\x00")
        with self.assertRaises(AudioFrameError):
            consumer.consume_frame(frame)

    def test_transcriber_returns_only_a_validated_final_transcript(self):
        sender = SecureAudioSender(self._session("client"), "stream-transcript")
        first = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        final = sender.seal_chunk(b"\x03\x04" * 4, final=True)
        receiver = SecureAudioReceiver(self._session("server"))
        retained_views: list[memoryview] = []

        def provider(view: memoryview, is_final: bool) -> str | None:
            retained_views.append(view)
            return "estado de integraciones" if is_final else None

        transcriber = SecureAudioTranscriber(receiver, provider, self._listening_gate())
        try:
            self.assertFalse(transcriber.consume_frame(first))
            self.assertTrue(transcriber.consume_frame(final))
            self.assertIsNone(transcriber.transcript)
            summary = transcriber.finalize()

            self.assertEqual(transcriber.transcript, "estado de integraciones")
            self.assertEqual(summary.stream_bytes, 16)
            with self.assertRaises(ValueError):
                len(retained_views[0])
        finally:
            transcriber.close()

    def test_transcriber_rejects_partial_or_unsafe_transcripts(self):
        sender = SecureAudioSender(self._session("client"), "stream-transcript-policy")
        first = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        receiver = SecureAudioReceiver(self._session("server"))

        partial = SecureAudioTranscriber(
            receiver,
            lambda _view, is_final: "parcial" if not is_final else "final",
            self._listening_gate(),
        )
        with self.assertRaises(AudioFrameError):
            partial.consume_frame(first)
        self.assertTrue(partial.closed)

        unsafe_sender = SecureAudioSender(self._session("client"), "stream-transcript-unsafe")
        unsafe_frame = unsafe_sender.seal_chunk(b"\x01\x02" * 4, final=True)
        unsafe_receiver = SecureAudioReceiver(self._session("server"))
        unsafe = SecureAudioTranscriber(
            unsafe_receiver,
            lambda _view, _is_final: "texto\u202eoculto",
            self._listening_gate(),
        )
        with self.assertRaises(AudioFrameError):
            unsafe.consume_frame(unsafe_frame)
        self.assertTrue(unsafe.closed)

    def test_transcriber_rejects_a_final_frame_without_a_transcript(self):
        sender = SecureAudioSender(self._session("client"), "stream-no-transcript")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=True)
        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, _is_final: None,
            self._listening_gate(),
        )
        try:
            self.assertTrue(transcriber.consume_frame(frame))
            with self.assertRaises(AudioFrameError):
                transcriber.finalize()
            self.assertTrue(transcriber.closed)
        finally:
            transcriber.close()

    def test_command_bridge_keeps_the_session_for_an_exact_empty_transcript(self):
        sender = SecureAudioSender(self._session("client"), "stream-no-speech")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=True)
        dispatched: list[str] = []
        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, _is_final: "",
            AudioCaptureGate(),
        )
        bridge = SecureAudioCommandBridge(
            transcriber,
            lambda transcript: dispatched.append(transcript) or [{"type": "ui_state"}],
        )
        self.assertTrue(transcriber.consumer.gate.mark_codec_ready(True))
        bridge.begin_capture(display_ready=True, consented=True, secure_transport_ready=True)

        self.assertTrue(bridge.consume_frame(frame))
        _summary, messages = bridge.finalize()

        self.assertEqual(dispatched, [""])
        self.assertEqual(messages, [{"type": "ui_state"}])
        self.assertEqual(transcriber.consumer.receiver.session.seal(b"ok")["sequence"], 0)

    def test_transcriber_resets_provider_state_when_capture_is_cancelled(self):
        sender = SecureAudioSender(self._session("client"), "stream-transcript-reset")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        reset_calls: list[bool] = []
        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, _is_final: None,
            self._listening_gate(),
            reset_provider=lambda: reset_calls.append(True),
        )

        self.assertFalse(transcriber.consume_frame(frame))
        transcriber.cancel()

        self.assertEqual(reset_calls, [True])
        self.assertFalse(transcriber.closed)
        self.assertIsNone(transcriber.transcript)
        transcriber.close()
        self.assertEqual(reset_calls, [True, True])

    def test_transcriber_closes_if_provider_reset_fails(self):
        sender = SecureAudioSender(self._session("client"), "stream-transcript-reset-failure")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, _is_final: None,
            self._listening_gate(),
            reset_provider=lambda: (_ for _ in ()).throw(RuntimeError("private provider state")),
        )

        self.assertFalse(transcriber.consume_frame(frame))
        with self.assertRaises(AudioFrameError):
            transcriber.cancel()

        self.assertTrue(transcriber.closed)

    def test_command_bridge_dispatches_only_a_final_transcript_and_closes(self):
        sender = SecureAudioSender(self._session("client"), "stream-bridge")
        first = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        final = sender.seal_chunk(b"\x03\x04" * 4, final=True)
        dispatched: list[str] = []

        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, is_final: "estado de integraciones" if is_final else None,
            AudioCaptureGate(),
        )
        bridge = SecureAudioCommandBridge(transcriber, dispatched.append)
        self.assertTrue(transcriber.consumer.gate.mark_codec_ready(True))
        bridge.begin_capture(display_ready=True, consented=True, secure_transport_ready=True)

        self.assertFalse(bridge.consume_frame(first))
        self.assertTrue(bridge.consume_frame(final))
        self.assertEqual(dispatched, [])

        summary, result = bridge.finalize()

        self.assertEqual(summary.stream_bytes, 16)
        self.assertIsNone(result)
        self.assertEqual(dispatched, ["estado de integraciones"])
        self.assertTrue(bridge.closed)
        # Successful finalization erases the audio provider/stream but keeps
        # the shared encrypted control session available for the response.
        self.assertEqual(sender.session.seal(b"ok")["sequence"], 2)
        with self.assertRaises(AudioFrameError):
            bridge.finalize()

    def test_command_bridge_closes_when_dispatch_fails(self):
        sender = SecureAudioSender(self._session("client"), "stream-bridge-failure")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=True)

        def fail(_transcript: str) -> None:
            raise RuntimeError("private dispatcher detail")

        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, _is_final: "estado del ordenador",
            self._listening_gate(),
        )
        bridge = SecureAudioCommandBridge(transcriber, fail)
        try:
            self.assertTrue(bridge.consume_frame(frame))
            with self.assertRaises(AudioFrameError):
                bridge.finalize()
            self.assertTrue(bridge.closed)
            self.assertNotIn("private dispatcher detail", str(bridge))
        finally:
            bridge.close()

    def test_command_bridge_closes_when_audio_finalization_fails(self):
        sender = SecureAudioSender(self._session("client"), "stream-bridge-truncated")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        dispatched: list[str] = []
        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, is_final: "no debe enviarse" if is_final else None,
            self._listening_gate(),
        )
        bridge = SecureAudioCommandBridge(transcriber, dispatched.append)
        try:
            self.assertFalse(bridge.consume_frame(frame))
            with self.assertRaises(AudioFrameError):
                bridge.finalize()
            self.assertTrue(bridge.closed)
            self.assertEqual(dispatched, [])
        finally:
            bridge.close()

    def test_command_bridge_cancel_clears_transcript_and_allows_a_new_capture(self):
        sender = SecureAudioSender(self._session("client"), "stream-bridge-cancel")
        partial = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        dispatched: list[str] = []
        transcriber = SecureAudioTranscriber(
            SecureAudioReceiver(self._session("server")),
            lambda _view, is_final: "estado de integraciones" if is_final else None,
            AudioCaptureGate(),
        )
        bridge = SecureAudioCommandBridge(transcriber, dispatched.append)
        try:
            self.assertTrue(transcriber.consumer.gate.mark_codec_ready(True))
            bridge.begin_capture(display_ready=True, consented=True, secure_transport_ready=True)
            self.assertFalse(bridge.consume_frame(partial))
            bridge.cancel()
            self.assertFalse(bridge.closed)

            second_sender = SecureAudioSender(sender.session, "stream-bridge-cancel-new")
            second = second_sender.seal_chunk(b"\x05\x06" * 4, final=True)
            bridge.begin_capture(display_ready=True, consented=True, secure_transport_ready=True)
            self.assertTrue(bridge.consume_frame(second))
            bridge.finalize()
            self.assertEqual(dispatched, ["estado de integraciones"])
        finally:
            bridge.close()

    def test_consumer_finalize_rejects_truncated_stream_and_closes_session(self):
        sender = SecureAudioSender(self._session("client"), "stream-truncated")
        frame = sender.seal_chunk(b"\x01\x02" * 4, final=False)
        receiver = SecureAudioReceiver(self._session("server"))
        consumer = SecureAudioConsumer(receiver, lambda _view, _final: None, self._listening_gate())

        self.assertFalse(consumer.consume_frame(frame))
        with self.assertRaises(AudioFrameError):
            consumer.finalize()

        self.assertTrue(consumer.closed)
        with self.assertRaises(ClosedSessionError):
            receiver.session.seal(b"\x00\x00")

    def test_consumer_cancel_reuses_control_session_for_a_new_stream(self):
        first_sender = SecureAudioSender(self._session("client"), "stream-cancelled")
        first = first_sender.seal_chunk(b"\x01\x02" * 4, final=False)
        receiver = SecureAudioReceiver(self._session("server"))
        received: list[bytes] = []
        gate = self._listening_gate()
        consumer = SecureAudioConsumer(receiver, lambda view, _final: received.append(bytes(view)), gate)

        self.assertFalse(consumer.consume_frame(first))
        consumer.cancel()
        self.assertEqual(gate.state, AudioCaptureState.CODEC_READY)
        consumer.begin_capture(display_ready=True, consented=True, secure_transport_ready=True)

        second_sender = SecureAudioSender(first_sender.session, "stream-new")
        second = second_sender.seal_chunk(b"\x03\x04" * 4, final=True)
        self.assertTrue(consumer.consume_frame(second))
        self.assertEqual(received, [b"\x01\x02" * 4, b"\x03\x04" * 4])


if __name__ == "__main__":
    unittest.main()
