import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secure_audio import (  # noqa: E402
    MAX_AUDIO_CHUNK_BYTES,
    MAX_AUDIO_CHUNKS,
    AudioFrameError,
    SecureAudioReceiver,
    SecureAudioSender,
)
from secure_session import secure_session_from_shared_secret  # noqa: E402

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

    def test_cancel_discards_stream_state_without_logging_or_reusing_samples(self):
        sender = SecureAudioSender(self._session("client"), "stream-five")
        sender.seal_chunk(b"\x01\x02" * 8, final=False)
        sender.cancel()
        with self.assertRaises(AudioFrameError):
            sender.seal_chunk(b"\x03\x04", final=True)


if __name__ == "__main__":
    unittest.main()
