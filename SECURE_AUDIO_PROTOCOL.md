# Contrato de audio cifrado v2

Este documento define la futura trama de audio entre un cliente autenticado y
Pipα. El contrato está implementado y probado en memoria, pero no activa el
micrófono, el altavoz, I²S, STT ni una capacidad de voz en el catálogo. La
captura seguirá bloqueada hasta validar físicamente el Waveshare, el indicador
de escucha y el consentimiento del usuario.

## Sesión y autenticación

El audio solo puede viajar dentro de una `SecureSession`/`PipaSecureRecordLayer`
v2 ya autenticada. Cada record mantiene el encabezado v2 existente
(`protocol_version`, `sequence`, `session_id`) y cifra el payload binario con
ChaCha20-Poly1305.

Los metadatos de audio no van cifrados para que el receptor pueda enrutar y
ordenar la trama, pero forman parte de los datos autenticados (AAD):

```text
AAD = UTF-8("pipa/audio/v2\0") + canonical_json(audio_metadata)
```

`canonical_json` usa UTF-8, claves ordenadas, separadores sin espacios y no
permite valores NaN o infinitos. Si un metadato cambia, la autenticación falla.

## Forma exacta de una trama

La trama debe contener exactamente estos campos, sin extensiones implícitas:

| Campo | Tipo | Regla |
| --- | --- | --- |
| `ciphertext` | base64url | Payload PCM cifrado; nunca muestras en claro |
| `protocol_version` | entero | `2`, procedente del record layer |
| `sequence` | entero | Secuencia monotónica de la sesión |
| `session_id` | string | Identificador de la sesión autenticada |
| `audio_protocol_version` | entero | `2` |
| `bits_per_sample` | entero | `16` |
| `channels` | entero | `1` |
| `chunk_index` | entero | Empieza en `0` y aumenta de uno en uno |
| `final` | booleano | Solo marca el último bloque |
| `sample_rate` | entero | `16000` Hz |
| `stream_id` | string | 1–64 caracteres ASCII `[A-Za-z0-9_-]` |

El payload descifrado es PCM little-endian mono de 16 bits. Los límites son
4096 bytes por bloque, 64 bloques y 262144 bytes por stream (aproximadamente
8,192 segundos). Un bloque no puede estar vacío ni tener un número impar de
bytes.

El receptor exige el bloque cero, el mismo `stream_id`, secuencias contiguas y
un único marcador `final`. Un bloque repetido, adelantado, cambiado,
demasiado grande o asociado a otra sesión cierra la sesión segura y descarta
el estado temporal. `cancel` solo limpia el stream y conserva la sesión de
control para poder iniciar otro stream; cerrar la sesión exige un handshake
nuevo.

## Implementaciones y pruebas

- Windows: `windows-agent/secure_audio.py`. `SecureAudioConsumer` exige un
  `AudioCaptureGate` en estado `LISTENING` antes de entregar cada bloque
  autenticado a un callback local mediante un `memoryview` efímero, borra el
  buffer al devolverlo y solo devuelve contadores acotados al finalizar. No
  acumula una grabación ni está conectado al agente residente.
- iPhone: `mobile-ios/Sources/PipaMobileCore/PipaSecureAudio.swift`.
- Firmware: `firmware/src/pipa_secure_audio.h/.cpp` contiene un primitive
  acotado de framing, cifrado y apertura, ejecutado únicamente por el vector
  `secure-session-vector`; no forma parte de la captura ni del transporte
  normal.
- Vector compartido: `mobile-ios/Tests/Fixtures/secure_audio_v2.json`.
- Tests Python y Swift: verifican ciphertext idéntico, ausencia de un campo
  `samples`, orden, límites, manipulación de metadatos y cierre fail-closed.

El módulo no se importa desde el agente residente. En firmware se compila como
una librería de transporte aislada, pero solo se invoca desde la prueba
protegida por `PIPA_SECURE_SESSION_VECTOR_TEST`; no tiene dependencias de I²S,
codec, Wi‑Fi, serie ni pantalla. No escribe muestras en logs, archivos, NVS o
pantalla y no tiene ninguna ruta de captura conectada. La integración real del
firmware queda deliberadamente para después de probar codec, I²S, buffers,
cancelación e indicador en la placa.

## Entrega al futuro STT

El consumidor de Windows es la única pieza preparada para recibir audio antes
de la integración física. Antes de usarlo, el futuro driver debe marcar el
codec como listo y llamar a `begin_capture(display_ready=True,
consented=True, secure_transport_ready=True)`. El `AudioCaptureGate` rechaza
cualquier otro orden y solo permite `CODEC_READY -> LISTENING -> DRAINING ->
CODEC_READY`; un fallo deja el estado en `ERROR`. El callback recibe
`(memoryview, final)` y debe procesar el bloque localmente; la vista se invalida
al volver del callback y el buffer temporal se pone a cero. El callback no debe
conservar una copia ni escribir audio en disco. Si falla, el consumidor cierra
la sesión segura. Si la secuencia termina sin `final`, también se cierra: una
transcripción parcial no se interpreta como un comando.

Todavía no existe un callback STT concreto, no se anuncia `voice`/`audio` en
las capacidades y `hold_end`/`audio_end` siguen respondiendo
`voice_unavailable`. Esa separación es intencionada hasta validar micrófono,
indicador visible, cancelación y rendimiento en el Waveshare.
