"""Safe, read-only smoke check for a connected Waveshare board.

The checker opens one explicitly selected serial port, sends no bytes and never
prints the serial stream. It only reports bounded, known boot markers, with the
public key represented as a validity flag and an optional fingerprint. This
makes it useful during first setup without turning a serial monitor dump into a
credential or privacy leak.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

EXPECTED_MARKERS = {
    "io_expander": "IO expander ready",
    "display": "display ready",
    "touch": "touch controller ready",
    "battery": "battery ADC ready",
}
_BOARD_REVISION_PATTERN = re.compile(r"^board revision:\s*(?P<revision>[12])$")
_MAX_DIAGNOSTIC_BYTES = 4_096
_MAX_FIXTURE_BYTES = 64 * 1024
_AUDIO_PROBE_READY = "audio codec probe ready"
_AUDIO_PROBE_UNAVAILABLE = "audio codecs not detected"
_AUDIO_OUTPUT_PRESENT = "audio output ES8311: present"
_AUDIO_OUTPUT_ABSENT = "audio output ES8311: absent"
_AUDIO_INPUT_PRESENT = "audio input ES7210: present"
_AUDIO_INPUT_ABSENT = "audio input ES7210: absent"
_PUBLIC_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _public_key_details(value: str) -> tuple[bool, str | None]:
    """Validate the device marker and derive a display-only fingerprint."""

    if _PUBLIC_KEY_PATTERN.fullmatch(value) is None:
        return False, None
    standard = value.replace("-", "+").replace("_", "/")
    try:
        decoded = base64.b64decode(standard + "=", validate=True)
    except (ValueError, binascii.Error):
        return False, None
    if len(decoded) != 32:
        return False, None
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if canonical != value:
        return False, None
    digest = hashlib.sha256(decoded).hexdigest().upper()
    return True, ":".join(digest[index : index + 2] for index in range(0, len(digest), 2))


@dataclass
class HardwareDiagnostics:
    """Bounded state extracted from safe, human-readable boot diagnostics."""

    lines_seen: int = 0
    public_key_seen: bool = False
    public_key_valid: bool = False
    _public_key_fingerprint: str | None = field(default=None, repr=False)
    board_revision: int | None = None
    ready_markers: set[str] = field(default_factory=set)
    unavailable_markers: set[str] = field(default_factory=set)
    fatal_seen: bool = False
    audio_probe_ready: bool | None = None
    audio_output_codec_present: bool | None = None
    audio_input_codec_present: bool | None = None

    def observe(self, raw_line: bytes | str) -> None:
        """Consume one line without retaining or echoing its contents."""

        if isinstance(raw_line, bytes):
            if len(raw_line) > _MAX_DIAGNOSTIC_BYTES:
                return
            line = raw_line.decode("utf-8", errors="replace")
        else:
            line = raw_line
        line = line.strip()
        if not line.startswith("#"):
            return

        self.lines_seen += 1
        message = line[1:].strip()
        if message.startswith("PIPA_PUBLIC_KEY="):
            public_key = message.removeprefix("PIPA_PUBLIC_KEY=").strip()
            self.public_key_seen = bool(public_key)
            self.public_key_valid, self._public_key_fingerprint = _public_key_details(public_key)
            return

        board_match = _BOARD_REVISION_PATTERN.fullmatch(message)
        if board_match:
            self.board_revision = int(board_match.group("revision"))
            return

        if message == _AUDIO_PROBE_READY:
            self.audio_probe_ready = True
            return
        if message == _AUDIO_PROBE_UNAVAILABLE:
            self.audio_probe_ready = False
            return
        if message == _AUDIO_OUTPUT_PRESENT:
            self.audio_output_codec_present = True
            return
        if message == _AUDIO_OUTPUT_ABSENT:
            self.audio_output_codec_present = False
            return
        if message == _AUDIO_INPUT_PRESENT:
            self.audio_input_codec_present = True
            return
        if message == _AUDIO_INPUT_ABSENT:
            self.audio_input_codec_present = False
            return

        for marker_name, marker_text in EXPECTED_MARKERS.items():
            if message == marker_text:
                self.ready_markers.add(marker_name)
                return
            if message == marker_text.replace(" ready", " unavailable"):
                self.unavailable_markers.add(marker_name)
                return

        if message.startswith("FATAL:"):
            self.fatal_seen = True

    def result(
        self,
        expected_board_revision: int,
        *,
        include_fingerprint: bool = False,
    ) -> dict[str, object]:
        """Return a stable report that contains no serial payloads."""

        failures: list[str] = []
        if self.lines_seen == 0:
            failures.append("no_boot_diagnostics")
        if not self.public_key_seen:
            failures.append("public_key_marker_missing")
        elif not self.public_key_valid:
            failures.append("public_key_marker_invalid")
        if self.board_revision != expected_board_revision:
            failures.append("unexpected_board_revision")
        for marker_name in EXPECTED_MARKERS:
            if marker_name not in self.ready_markers:
                failures.append(f"{marker_name}_not_ready")
        if self.fatal_seen:
            failures.append("fatal_boot_error")

        report: dict[str, object] = {
            "success": not failures,
            "lines_seen": self.lines_seen,
            "public_key_seen": self.public_key_seen,
            "public_key_valid": self.public_key_valid,
            "board_revision": self.board_revision,
            "expected_board_revision": expected_board_revision,
            "ready": {name: name in self.ready_markers for name in EXPECTED_MARKERS},
            "unavailable": {name: name in self.unavailable_markers for name in EXPECTED_MARKERS},
            "audio": {
                "probe_ready": self.audio_probe_ready,
                "output_codec_present": self.audio_output_codec_present,
                "input_codec_present": self.audio_input_codec_present,
            },
            "fatal_seen": self.fatal_seen,
            "failures": failures,
        }
        if include_fingerprint and self._public_key_fingerprint is not None:
            report["public_key_fingerprint"] = self._public_key_fingerprint
        return report


def _port(value: str) -> str:
    clean = value.strip()
    if platform.system() == "Windows":
        if re.fullmatch(r"COM(?:[1-9][0-9]{0,2})", clean.upper()) is None:
            raise argparse.ArgumentTypeError("El puerto debe ser COM1 a COM999.")
        return clean.upper()
    if re.fullmatch(r"/dev/[A-Za-z0-9._/-]+", clean) is None:
        raise argparse.ArgumentTypeError("El puerto debe ser una ruta /dev explícita.")
    return clean


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Comprobación serie segura de Pipa.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--port",
        type=_port,
        default=None,
        help="Puerto explícito; si se omite usa PIPA_SERIAL_PORT.",
    )
    source.add_argument(
        "--fixture",
        help="Fixture local de diagnóstico; no abre ningún puerto ni valida hardware real.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=8.0,
        help="Segundos de escucha pasiva (0.5 a 120).",
    )
    parser.add_argument(
        "--expected-board-revision",
        type=int,
        choices=(1, 2),
        default=2,
        help="Revisión esperada; el SKU actual usa V2 por defecto.",
    )
    parser.add_argument("--json", action="store_true", help="Devuelve solo JSON acotado.")
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="Incluye solo la huella SHA-256 de la clave pública detectada.",
    )
    return parser


def _collect(port: str, duration: float) -> HardwareDiagnostics:
    try:
        import serial
    except ImportError as error:
        raise RuntimeError("pyserial no está instalado en el entorno del agente.") from error

    diagnostics = HardwareDiagnostics()
    deadline = time.monotonic() + duration
    try:
        with serial.Serial(
            port=port,
            baudrate=115200,
            timeout=min(0.25, duration),
            write_timeout=1,
            dsrdtr=False,
            rtscts=False,
            xonxoff=False,
        ) as connection:
            while time.monotonic() < deadline:
                diagnostics.observe(connection.readline())
    except Exception as error:
        raise RuntimeError("no se pudo abrir o leer el puerto serie seleccionado.") from error
    return diagnostics


def _collect_fixture(path: str) -> HardwareDiagnostics:
    """Parse a bounded local transcript without opening a serial port."""

    if not isinstance(path, str) or not path.strip():
        raise RuntimeError("el fixture de hardware no es válido")
    try:
        raw = Path(path).read_bytes()
    except (OSError, ValueError) as error:
        raise RuntimeError("no se pudo leer el fixture de hardware") from error
    if len(raw) > _MAX_FIXTURE_BYTES:
        raise RuntimeError("el fixture de hardware es demasiado grande")

    diagnostics = HardwareDiagnostics()
    for line in raw.splitlines(keepends=True):
        diagnostics.observe(line)
    return diagnostics


def _human_report(port: str, report: dict[str, object]) -> str:
    ready = report["ready"]
    assert isinstance(ready, dict)
    labels = {
        "io_expander": "Expansor IO",
        "display": "Pantalla",
        "touch": "Touch",
        "battery": "ADC batería",
    }
    audio = report["audio"]
    assert isinstance(audio, dict)
    lines = [
        f"Puerto serie: {port}",
        f"Diagnósticos recibidos: {report['lines_seen']}",
        f"Revisión detectada: V{report['board_revision'] or '?'} "
        f"(esperada V{report['expected_board_revision']})",
        "Identidad pública detectada: sí (valor oculto)"
        if report["public_key_seen"]
        else "Identidad pública detectada: no",
    ]
    if report.get("public_key_fingerprint") is not None:
        lines.append(f"Fingerprint de identidad pública: {report['public_key_fingerprint']}")
    lines.extend(f"{labels[name]}: {'OK' if ready[name] else 'pendiente/fallo'}" for name in labels)
    if audio["probe_ready"] is not None:
        lines.append("Sonda audio: " + ("OK" if audio["probe_ready"] else "no detectada"))
    if audio["output_codec_present"] is not None:
        lines.append("Codec salida ES8311: " + ("presente" if audio["output_codec_present"] else "ausente"))
    if audio["input_codec_present"] is not None:
        lines.append("Codec entrada ES7210: " + ("presente" if audio["input_codec_present"] else "ausente"))
    if report["fatal_seen"]:
        lines.append("Arranque fatal detectado: sí")
    failures = report["failures"]
    if failures:
        lines.append("Resultado: PENDIENTE (" + ", ".join(failures) + ")")
    else:
        lines.append("Resultado: OK")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not 0.5 <= arguments.duration <= 120:
        print("Error: --duration debe estar entre 0.5 y 120 segundos.", file=sys.stderr)
        return 2
    source_label = "fixture local"
    try:
        if arguments.fixture:
            diagnostics = _collect_fixture(arguments.fixture)
        else:
            port = arguments.port
            if not port:
                configured_port = os.environ.get("PIPA_SERIAL_PORT", "").strip()
                if configured_port:
                    try:
                        port = _port(configured_port)
                    except argparse.ArgumentTypeError as error:
                        print(f"Error: {error}", file=sys.stderr)
                        return 2
            if not port:
                print("Error: indica --port COM7 o configura PIPA_SERIAL_PORT.", file=sys.stderr)
                return 2
            source_label = port
            diagnostics = _collect(port, arguments.duration)
        report = diagnostics.result(
            arguments.expected_board_revision,
            include_fingerprint=arguments.fingerprint,
        )
    except RuntimeError as error:
        if arguments.json:
            print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=False))
        else:
            print(f"Error: {error}", file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(_human_report(source_label, report))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
