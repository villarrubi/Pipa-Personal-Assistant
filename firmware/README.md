# Firmware Pipα

Reservado para el firmware del ESP32/Waveshare. El contrato inicial está en
[`backend/pipa_core/protocol.py`](../backend/pipa_core/protocol.py) y en el
README del backend.

El dispositivo deberá implementar como mínimo:

- `hello` autenticado con desafío/respuesta Ed25519.
- `wake`, `hold_start`, `hold_end`, `audio_end` y `abort`.
- `text_input` como fallback sin micrófono.
- `confirm` para aprobar o rechazar acciones.
- Renderizado de `ui_state`, `confirm_request`, `tool_result` y `error`.

No se asume todavía el modelo exacto de Waveshare, pantalla, micrófono ni
codec. Esa capa se conectará cuando tengamos el hardware real.
