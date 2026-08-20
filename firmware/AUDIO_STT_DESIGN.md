# Diseño de audio y voz de Pipα

Este documento describe la ruta de voz implementada para la revisión V2. El
entorno normal permanece sin captura, mientras que `voice-v2` inicializa el
ES7210 y la entrada I²S, muestra el estado de escucha, cifra PCM y lo entrega
al STT español local del PC. El altavoz y el amplificador permanecen apagados.

La compuerta de software de esas transiciones está en
`firmware/src/pipa_audio_state.h/.cpp`. Es independiente de Arduino y se
prueba en el vector seguro: ningún driver puede pasar de `PROBE_ONLY` a
`CODEC_READY` sin declarar una inicialización física correcta, ni entrar en
`LISTENING` sin pantalla, consentimiento y transporte seguro. La compuerta no
captura audio por sí misma. Su `vectorSelfTest()` también se ejecuta en host en
CI, para probar las transiciones sin necesitar una placa.

## Hardware objetivo

El objetivo es la revisión V2 del ESP32-S3-Touch-LCD-1.85C-BOX (SKU 30684).
La revisión V1 tiene un circuito de audio diferente y no puede reutilizar este
mapa sin una selección explícita de PIPA_BOARD_REVISION.

| Señal V2 | GPIO | Uso previsto |
| --- | ---: | --- |
| I2S MCLK | 2 | reloj del codec |
| I2C SCL / SDA | 10 / 11 | configuración ES8311/ES7210 |
| PA_CTRL | 15 | amplificador, apagado durante la sonda |
| I2S LRCK | 38 | reloj de palabra |
| Mic data | 39 | datos del micrófono digital |
| I2S DIN | 47 | entrada del codec |
| I2S BCK | 48 | reloj de bits |

La fuente de verdad del pinout y de la variante es la
[documentación oficial de Waveshare](https://docs.waveshare.com/ESP32-S3-Touch-LCD-1.85C).
Antes de flashear se debe comprobar la serigrafía Rev2.0 o el firmware de
fábrica; el SKU por sí solo no basta.

## Estados

La capacidad anunciada y el comportamiento de audio deben seguir esta
máquina, sin saltos implícitos:

~~~text
DISABLED -> PROBE_ONLY -> CODEC_READY -> LISTENING
                         |              |
                         +-> ERROR <----+
LISTENING -> DRAINING -> CODEC_READY
~~~

- DISABLED: revisión desconocida, configuración incompleta o transporte
  inseguro. No se inicializa captura ni amplificador.
- PROBE_ONLY: sonda I²C no destructiva. No escribe registros del codec, no
  activa PA_CTRL y no anuncia capacidad de audio.
- CODEC_READY: la inicialización física de codec, I²S y clocks ha pasado.
  Solo entonces se puede anunciar una capacidad específica y limitada.
- LISTENING: captura con consentimiento y un indicador visible en pantalla.
  Tiene duración y memoria máximas; cancelar debe ser inmediato.
- DRAINING: se descartan y limpian los buffers temporales antes de volver a
  CODEC_READY.
- ERROR: cualquier fallo de codec, I²S, buffer o transporte desactiva audio
  hasta una nueva inicialización controlada.

La compilación correcta nunca equivale a CODEC_READY. El hello solo puede
anunciar una capacidad después de la inicialización real y del autotest mínimo
en la placa.

## Invariantes de seguridad

1. No se envía audio por el protocolo v1 ni como texto JSON.
2. Si el audio sale del dispositivo, cada bloque usa el record layer v2
   autenticado y cifrado; la firma Ed25519 por sí sola no proporciona
   confidencialidad.
3. Los bloques tienen un tamaño, una duración total y una cantidad total
   estrictamente acotados. El agente rechaza secuencias incompletas, repetidas,
   fuera de orden o con una sesión distinta.
4. No se escriben muestras, transcripciones, teléfonos, mensajes ni tokens en
   logs, NVS, la pantalla ni artefactos de diagnóstico.
5. Al cancelar, terminar, desconectar o caducar la sesión se pone a cero la
   memoria temporal antes de liberarla. Un error no devuelve datos del buffer.
6. La pantalla muestra un indicador de standby en el build manos libres y un
   estado `LISTEN` inequívoco durante el stream. Sin configuración explícita,
   pantalla operativa y transporte autenticado no se envía audio.
7. El amplificador permanece apagado durante la sonda, el arranque, los errores
   y la captura, salvo que una futura prueba de reproducción lo habilite de
   manera explícita.
8. La captura no puede bloquear el loop de autenticación, heartbeat, touch o
   apagado seguro.

## Reconocimiento de voz

El ESP32 no interpreta el habla. Captura PCM mono a 16 kHz y lo envía cifrado
por USB a `LocalSpeechTranscriber`, que ejecuta Faster-Whisper en el PC con
idioma español y `compute_type=int8`. El modelo predeterminado es `base` y se
guarda bajo `%LOCALAPPDATA%\Pipa\models`; no se usa una API de voz ni se crean
WAV temporales.

`voice-v2` conserva el flujo manual: un toque inicia la escucha, el usuario
habla y un segundo toque la finaliza, con un máximo de ocho segundos.
`voice-v2-handsfree` es una variante explícita: un VAD local adapta su umbral
al ruido de la sala, conserva unos 384 ms de pre-roll solo en RAM, inicia el
stream cifrado al detectar voz y lo finaliza tras unos 896 ms de silencio. El
límite de 30 segundos es únicamente una barrera ante ruido continuo o un fallo
de endpoint, no la duración normal de escucha.

El agente ignora las conversaciones que no empiecen por la frase local
configurada. Acepta la instrucción en la misma transcripción o arma durante un
intervalo corto la siguiente frase después de «Pipa, ¿me escuchas?». La
transcripción final pasa por el mismo parser, catálogo y barreras de ejecución
que el texto. El punto verde de la cara indica monitorización local; la
pantalla `LISTEN` aparece antes de que cualquier PCM salga cifrado por USB.

### Suspensión del PC

Tras 15 segundos sin respuestas autenticadas, la variante manos libres da por
ausente al agente. Si hay Wi-Fi y detecta una intervención, envía Wake-on-LAN
y guarda como máximo 32,768 segundos de PCM en PSRAM volátil. Al volver USB v2,
el bloque entra por el mismo receptor autenticado y se sobrescribe
progresivamente. Nunca se envía audio por UDP ni se escribe en NVS o flash. El
ESP32 solo detecta actividad, no palabras: un falso positivo puede despertar
Windows, aunque la frase obligatoria evita que ejecute órdenes.

## Ruta implementada

1. Se identifica la revisión V2 y se inicializan pantalla, touch e I²C.
2. El ES7210 se configura a 16 kHz/16 bits y la entrada estéreo se reduce a
   mono; PA_CTRL permanece apagado.
3. La placa solo anuncia `audio_capture` si códec e I²S llegan a
   `CODEC_READY` dentro de una sesión segura V2.
4. Cada bloque PCM se cifra con el contrato de
   [SECURE_AUDIO_PROTOCOL.md](../SECURE_AUDIO_PROTOCOL.md).
5. El agente autentica, ordena y descifra los bloques en memoria, ejecuta STT
   local y borra los buffers temporales.
6. El Core interpreta la frase y conserva todas sus barreras de confirmación.

## Criterios de aceptación

- Sin placa o con revisión incorrecta: no hay captura, reproducción ni
  capacidad audio; el diagnóstico sigue siendo seguro.
- Micrófono desconectado, codec ausente o I²S bloqueado: estado ERROR,
  amplificador apagado y recuperación por método normal.
- Cancelar una escucha no deja un buffer reutilizable ni una confirmación
  pendiente.
- Un frame de audio alterado, repetido, demasiado grande o fuera de orden
  cierra la sesión v2 y no llega al parser de voz.
- Una acción derivada de voz sigue necesitando la confirmación visible prevista
  para cualquier integración externa: WhatsApp, Discord, Apple Music, League o
  navegador.

La referencia oficial de ejemplos de audio del fabricante está en el
[repositorio oficial de Waveshare](https://github.com/waveshareteam/ESP32-S3-Touch-LCD-1.85C).
Es material de integración de hardware, no una autorización para relajar estos
límites.
