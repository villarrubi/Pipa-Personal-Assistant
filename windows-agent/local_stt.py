"""Private, in-memory Spanish speech recognition for authenticated Pipa audio."""

from __future__ import annotations

import math
import os
import threading
from pathlib import Path
from typing import Any

from secure_audio import AUDIO_SAMPLE_RATE, MAX_AUDIO_STREAM_BYTES
from tools.text_policy import validate_bounded_text

DEFAULT_MODEL = "base"
SUPPORTED_MODELS = frozenset({"tiny", "base", "small"})
MIN_AUDIO_BYTES = AUDIO_SAMPLE_RATE  # 0.5 seconds of 16-bit mono PCM
COMMAND_HOTWORDS = (
    "Pipa, Pipa me escuchas, ordenador, PC, Codex, calculadora, navegador, "
    "Chrome, WhatsApp, Discord, Apple Music, League of Legends, LoL, "
    "temporizador, volumen, batería, red, silencia, suspende"
)
COMMAND_CONTEXT = (
    "Órdenes breves en español para Pipa: Pipa me escuchas; estado del ordenador; "
    "estado de integraciones; estado de la red; estado de batería; abre calculadora; "
    "abre navegador; abre Codex; abre WhatsApp; abre Discord; abre Apple Music; "
    "abre League of Legends; busca en internet; pon el volumen; silencia el ordenador; "
    "activa el sonido; siguiente canción; crea, lista o cancela un temporizador; "
    "bloquea o suspende el ordenador."
)
TARGET_AUDIO_REFERENCE = 0.72
MAX_AUDIO_GAIN = 8.0
MIN_AUDIO_REFERENCE = 1.0 / 32768.0


class LocalSttError(RuntimeError):
    """The local model could not produce a safe final transcript."""


def default_model_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise LocalSttError("local model storage is unavailable")
    return Path(local_app_data) / "Pipa" / "models"


class LocalSpeechTranscriber:
    """Accumulate one bounded PCM stream and transcribe it locally.

    The model is shared between captures, while microphone samples remain in
    a per-capture mutable buffer that is overwritten on success, reset or
    failure. No temporary WAV file is created.
    """

    _models: dict[tuple[str, str, str, str], Any] = {}
    _model_lock = threading.RLock()

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        model_directory: Path | None = None,
    ) -> None:
        selected_model = (model_name or os.environ.get("PIPA_STT_MODEL") or DEFAULT_MODEL).strip()
        if selected_model not in SUPPORTED_MODELS:
            raise LocalSttError("unsupported local speech model")
        selected_device = (device or os.environ.get("PIPA_STT_DEVICE") or "cpu").strip().lower()
        if selected_device not in {"cpu", "cuda"}:
            raise LocalSttError("unsupported local speech device")
        selected_compute = (
            (
                compute_type
                or os.environ.get("PIPA_STT_COMPUTE_TYPE")
                or ("int8" if selected_device == "cpu" else "float16")
            )
            .strip()
            .lower()
        )
        if selected_compute not in {"int8", "float16", "int8_float16"}:
            raise LocalSttError("unsupported local speech compute type")

        self.model_name = selected_model
        self.device = selected_device
        self.compute_type = selected_compute
        self.model_directory = Path(model_directory or default_model_directory()).resolve()
        self._pcm = bytearray()
        self._diagnostics: dict[str, object] = {}

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return bounded signal/model metadata without exposing PCM."""

        return dict(self._diagnostics)

    def prepare(self) -> None:
        """Download/load the configured model without accepting microphone data."""

        self._model()

    def __call__(self, samples: memoryview, final: bool) -> str | None:
        if not isinstance(samples, memoryview) or not isinstance(final, bool):
            self.reset()
            raise LocalSttError("invalid local speech input")
        if len(self._pcm) + samples.nbytes > MAX_AUDIO_STREAM_BYTES:
            self.reset()
            raise LocalSttError("local speech input is too large")
        self._pcm.extend(samples)
        if not final:
            return None
        if len(self._pcm) < MIN_AUDIO_BYTES:
            self.reset()
            raise LocalSttError("local speech input is too short")
        return self._transcribe_final()

    def reset(self) -> None:
        if self._pcm:
            self._pcm[:] = b"\x00" * len(self._pcm)
            self._pcm.clear()

    def _model(self):
        key = (self.model_name, self.device, self.compute_type, str(self.model_directory))
        with self._model_lock:
            model = self._models.get(key)
            if model is not None:
                return model
            try:
                from faster_whisper import WhisperModel

                self.model_directory.mkdir(parents=True, exist_ok=True)
                model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(self.model_directory),
                )
            except Exception as error:
                raise LocalSttError("local speech model is unavailable") from error
            self._models[key] = model
            return model

    def _transcribe_final(self) -> str:
        self._diagnostics = {}
        audio = None
        try:
            import numpy as np

            # Whisper accepts normalized float32 PCM directly, so samples do
            # not need to be written to a WAV or another temporary file.
            audio = np.frombuffer(self._pcm, dtype="<i2").astype(np.float32)
            audio *= 1.0 / 32768.0
            raw_clipped_percent = float(np.mean(np.abs(audio) >= (32767.0 / 32768.0))) * 100.0
            audio -= float(np.mean(audio, dtype=np.float64))
            absolute = np.abs(audio)
            peak = float(np.max(absolute))
            rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
            reference = float(np.percentile(absolute, 99.0))
            gain = 1.0
            if reference >= MIN_AUDIO_REFERENCE:
                gain = min(MAX_AUDIO_GAIN, max(0.5, TARGET_AUDIO_REFERENCE / reference))
                audio *= gain
            clipped_percent = float(np.mean(np.abs(audio) >= 0.999)) * 100.0
            np.clip(audio, -1.0, 1.0, out=audio)

            raw_segments, information = self._model().transcribe(
                audio,
                language="es",
                task="transcribe",
                beam_size=5,
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.35,
                    "min_speech_duration_ms": 120,
                    "min_silence_duration_ms": 250,
                    "speech_pad_ms": 180,
                },
                condition_on_previous_text=False,
                hotwords=COMMAND_HOTWORDS,
                initial_prompt=COMMAND_CONTEXT,
                temperature=0.0,
            )
            segments = list(raw_segments)
            durations = [
                max(0.0, float(getattr(segment, "end", 0.0)) - float(getattr(segment, "start", 0.0)))
                for segment in segments
            ]
            weights = [duration if duration > 0 else 1.0 for duration in durations]
            total_weight = sum(weights)
            average_log_probability = sum(
                float(getattr(segment, "avg_logprob", 0.0)) * weight
                for segment, weight in zip(segments, weights, strict=True)
            ) / max(1.0, total_weight)
            no_speech_probability = sum(
                float(getattr(segment, "no_speech_prob", 0.0)) * weight
                for segment, weight in zip(segments, weights, strict=True)
            ) / max(1.0, total_weight)
            self._diagnostics = {
                "model": self.model_name,
                "device": self.device,
                "audio_duration_ms": round(len(audio) * 1000 / AUDIO_SAMPLE_RATE),
                "peak_dbfs": _dbfs(peak),
                "rms_dbfs": _dbfs(rms),
                "reference_dbfs": _dbfs(reference),
                "raw_clipped_percent": round(raw_clipped_percent, 4),
                "applied_gain_db": round(20.0 * math.log10(gain), 2),
                "clipped_percent": round(clipped_percent, 4),
                "segment_count": len(segments),
                "speech_duration_ms": round(sum(durations) * 1000),
                "average_log_probability": round(average_log_probability, 4),
                "no_speech_probability": round(no_speech_probability, 4),
                "language_probability": round(float(getattr(information, "language_probability", 0.0)), 4),
            }
            transcript = " ".join(
                segment.text.strip() for segment in segments if segment.text.strip()
            ).strip()
            if not transcript:
                return ""
            return validate_bounded_text(transcript, "La transcripción", 4000).strip()
        except (LocalSttError, ValueError):
            raise
        except Exception as error:
            raise LocalSttError("local speech transcription failed") from error
        finally:
            if audio is not None:
                audio.fill(0)
            self.reset()


def _dbfs(amplitude: float) -> float:
    return round(20.0 * math.log10(max(amplitude, 1.0 / 65536.0)), 2)
