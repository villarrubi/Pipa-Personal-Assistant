"""Download and validate Pipa's local speech model without recording audio."""

from __future__ import annotations

import argparse

from local_stt import DEFAULT_MODEL, SUPPORTED_MODELS, LocalSpeechTranscriber, LocalSttError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepara el modelo STT local de Pipa.")
    parser.add_argument("--model", choices=sorted(SUPPORTED_MODELS), default=DEFAULT_MODEL)
    arguments = parser.parse_args(argv)
    try:
        transcriber = LocalSpeechTranscriber(model_name=arguments.model)
        transcriber.prepare()
    except LocalSttError:
        print("No se pudo preparar el modelo de voz local.")
        return 1
    print(f"Modelo de voz local preparado: {arguments.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
