# Contrato de audio cifrado v2

Este documento define la trama de audio entre un cliente autenticado y Pipα.
Está integrada de extremo a extremo en el entorno opt-in `voice-v2`: captura
ES7210/I²S en la placa, transporte cifrado por USB y STT español local en el
PC. Los builds normales no activan captura y el altavoz permanece apagado.

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
  buffer al devolverlo y solo devuelve contadores acotados al finalizar. El
  receptor convierte el plaintext a un `bytearray` en la frontera criptográfica
  para que también pueda ponerse a cero en las rutas de error; no expone
  muestras como texto ni escribe grabaciones. El gateway V2 lo conecta al
  agente residente únicamente cuando `PIPA_VOICE_ENABLED=1`.
- Windows también incluye `SecureAudioTranscriber`, un adaptador inyectable
  que entrega esos chunks al proveedor STT y acepta únicamente una
  transcripción final validada por la política de texto. Un proveedor
  STT que mantenga estado de streaming debe proporcionar `reset_provider` para
  que cancelar, cerrar o fallar el stream borre su estado antes de reutilizarlo;
  si ese reinicio falla, el transcriptor se cierra y no acepta otra captura.
- `SecureAudioCommandBridge` encapsula el paso siguiente: solo después de
  finalizar el stream entrega una única transcripción al dispatcher del Core y
  cierra el transcriptor tanto si el dispatcher termina correctamente como si
  falla. Cancelar conserva únicamente la sesión de control para una captura
  posterior; no conserva el transcript.
- iPhone: `mobile-ios/Sources/PipaMobileCore/PipaSecureAudio.swift`.
- Firmware: `firmware/src/pipa_secure_audio.h/.cpp` contiene el primitive
  acotado de framing y cifrado. Se compila para el vector y para `voice-v2`;
  `pipa_secure_protocol.cpp` es la única ruta de producción que lo transmite.
- Vector compartido: `mobile-ios/Tests/Fixtures/secure_audio_v2.json`.
- Tests Python y Swift: verifican ciphertext idéntico, ausencia de un campo
  `samples`, orden, límites, manipulación de metadatos y cierre fail-closed.

El framing sigue sin depender de I²S, codec, Wi‑Fi, serie ni pantalla. El
gateway residente lo recibe solo sobre la sesión V2 autenticada y lo entrega a
`windows-agent/local_stt.py`. Ninguna de las capas escribe muestras en logs,
archivos, NVS o pantalla.

## Entrega al STT local

Antes de usarlo, el driver debe marcar el
codec como listo y llamar a `begin_capture(display_ready=True,
consented=True, secure_transport_ready=True)`. El `AudioCaptureGate` rechaza
cualquier otro orden y solo permite `CODEC_READY -> LISTENING -> DRAINING ->
CODEC_READY`; un fallo deja el estado en `ERROR`. El callback recibe
`(memoryview, final)` y debe procesar el bloque localmente; la vista se invalida
al volver del callback y el buffer temporal se pone a cero. El callback no debe
conservar una copia ni escribir audio en disco. Si falla, el consumidor cierra
la sesión segura. Si la secuencia termina sin `final`, también se cierra: una
transcripción parcial no se interpreta como un comando. Después de obtener una
transcripción final, el adaptador debe entregarla a
`PipaCore.handle_transcript`; el Core la valida otra vez y usa exactamente el
mismo parser, confirmación y redacción que `text_input`.

El callback concreto es `LocalSpeechTranscriber`, basado en Faster-Whisper y
configurado en español. La placa anuncia `audio_capture` solo después de
inicializar físicamente el ES7210/I²S. `voice_ready` en `/pipa/protocol`
confirma que agente, sesión, capacidad y estado `codec_ready` coinciden.
