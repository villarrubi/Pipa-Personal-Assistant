import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from local_stt import LocalSpeechTranscriber, LocalSttError  # noqa: E402


class LocalSttTests(unittest.TestCase):
    def test_transcribes_pcm_in_memory_and_zeroes_capture_buffers(self):
        class FakeModel:
            def __init__(self):
                self.audio = None
                self.options = None

            def transcribe(self, audio, **options):
                self.audio = audio
                self.options = options
                return iter(
                    [
                        SimpleNamespace(
                            text=" estado del ordenador ",
                            start=0.25,
                            end=1.5,
                            avg_logprob=-0.15,
                            no_speech_prob=0.02,
                        )
                    ]
                ), SimpleNamespace(language_probability=0.99)

        provider = LocalSpeechTranscriber(model_directory=ROOT / ".platformio-preflight" / "stt-test")
        model = FakeModel()
        with patch.object(provider, "_model", return_value=model):
            transcript = provider(memoryview(b"\x00\x01\x00\xff" * 4000), True)

        self.assertEqual(transcript, "estado del ordenador")
        self.assertEqual(provider._pcm, bytearray())
        self.assertTrue((model.audio == 0).all())
        self.assertEqual(model.options["language"], "es")
        self.assertFalse(model.options["vad_filter"])
        self.assertIn("ordenador", model.options["hotwords"])
        self.assertIn("Pipa me escuchas", model.options["hotwords"])
        self.assertIn("estado del ordenador", model.options["initial_prompt"])
        self.assertEqual(model.options["temperature"], 0.0)
        self.assertEqual(provider.diagnostics["segment_count"], 1)
        self.assertEqual(provider.diagnostics["speech_duration_ms"], 1250)
        self.assertEqual(provider.diagnostics["language_probability"], 0.99)
        self.assertGreater(provider.diagnostics["applied_gain_db"], 0)
        self.assertIn("reference_dbfs", provider.diagnostics)
        self.assertIn("raw_clipped_percent", provider.diagnostics)

    def test_reports_adc_saturation_before_normalization(self):
        class FakeModel:
            def transcribe(self, _audio, **_options):
                return iter([]), SimpleNamespace(language_probability=1.0)

        provider = LocalSpeechTranscriber(model_directory=ROOT / ".platformio-preflight" / "stt-test")
        saturated_pcm = b"\xff\x7f\x00\x80" * 4000
        with patch.object(provider, "_model", return_value=FakeModel()):
            provider(memoryview(saturated_pcm), True)

        self.assertEqual(provider.diagnostics["raw_clipped_percent"], 100.0)

    def test_rejects_unbounded_model_selection(self):
        with self.assertRaises(LocalSttError):
            LocalSpeechTranscriber(model_name="remote/custom-model")

    def test_no_speech_returns_an_exact_empty_transcript_and_zeroes_audio(self):
        class SilentModel:
            def __init__(self):
                self.audio = None

            def transcribe(self, audio, **_options):
                self.audio = audio
                return iter([]), SimpleNamespace(language_probability=1.0)

        provider = LocalSpeechTranscriber(model_directory=ROOT / ".platformio-preflight" / "stt-test")
        model = SilentModel()
        with patch.object(provider, "_model", return_value=model):
            transcript = provider(memoryview(b"\x00\x01\x00\xff" * 4000), True)

        self.assertEqual(transcript, "")
        self.assertEqual(provider.diagnostics["segment_count"], 0)
        self.assertEqual(provider._pcm, bytearray())
        self.assertTrue((model.audio == 0).all())


if __name__ == "__main__":
    unittest.main()
