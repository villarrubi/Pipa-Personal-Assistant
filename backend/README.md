# Pipα Core

Núcleo independiente del transporte para sesiones de dispositivo, protocolo,
estado de UI, memoria temporal, herramientas y confirmaciones. Hoy se aloja
dentro del Windows Agent y se usa tanto desde USB serie como desde el
WebSocket local `/pipa/ws`.

## Autenticación

1. El dispositivo emparejado envía `challenge_request` con su `device_id`.
2. El Core devuelve un desafío corto con nonce, operación, audiencia y
   caducidad.
3. El dispositivo firma el JSON canónico completo con su clave Ed25519.
4. Envía `hello` con `challenge_id`, firma y metadatos opcionales.
5. El Core consume el desafío y crea una sesión temporal.

Para compatibilidad local también existe `POST /pipa/challenge`; el flujo
preferido mantiene desafío y sesión en el mismo transporte.

La política de conexión está centralizada en `pipa_core/connection.py`: USB y
WebSocket comparten rate limit, máximo de fallos, timeout y cleanup. Las
claves privadas no existen en este módulo ni se persisten en Windows.

## Mensajes de protocolo v1

Antes de autenticar:

- `challenge_request`
- `hello`

Después de autenticar:

- `ping`, `device_status`
- `wake`, `hold_start`, `hold_end`, `audio_end`, `abort`
- `gesture`, `text_input`
- `tool_call`, `confirm`

El parser rechaza versiones desconocidas, campos inesperados, textos y listas
fuera de límite, telemetría inválida y tipos ambiguos. Cambios incompatibles
requieren aumentar `protocol_version`.

## Herramientas y confirmaciones

Las herramientas `unsafe` no se ejecutan al primer mensaje. El Core devuelve
`confirm_request`; su identificador pertenece a la sesión que lo creó, caduca
en 30 segundos y solo puede consumirse una vez.

El adaptador de frases en español es deliberadamente determinista. Una futura
capa STT/LLM debe producir `text_input` o `tool_call`; no debe mezclarse con
los handlers que controlan Windows.

`remember_fact` y `recall_memory` usan memoria de proceso, acotada por
dispositivo. No se persisten datos personales hasta diseñar cifrado, borrado y
exportación.

## Simulador

```powershell
python backend/pipa_simulator.py
```

Genera una identidad efímera en RAM, completa la autenticación y ejecuta una
herramienta inocua. No modifica Windows ni escribe claves.

## Pruebas

```powershell
python -B -m unittest discover -s backend/tests -p "test_*.py"
```
