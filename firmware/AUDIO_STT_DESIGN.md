# Diseño de audio y voz de Pipα

Este documento fija el contrato de la futura capa de audio antes de tocar la
placa física. No habilita todavía micrófono, altavoz, I²S ni reconocimiento de
voz. El firmware actual permanece en modo audio_probe: solo comprueba
presencia I²C y mantiene el amplificador apagado.

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
6. La pantalla muestra un estado de escucha inequívoco. Sin indicador visible
   y confirmación de la acción no se captura.
7. El amplificador permanece apagado durante la sonda, el arranque, los errores
   y la captura, salvo que una futura prueba de reproducción lo habilite de
   manera explícita.
8. La captura no puede bloquear el loop de autenticación, heartbeat, touch o
   apagado seguro.

## Reconocimiento de voz

La primera versión no debe prometer STT español dentro del ESP32. La ruta
oficial de ESP-SR se evaluará solo después de la prueba física y de confirmar
qué modelos soporta realmente; no se activará un modelo por defecto como si
fuera reconocimiento español.

Las opciones que se compararán con datos medidos son:

- dictado local del iPhone, que ya exige reconocimiento en dispositivo y solo
  rellena el editor;
- STT local del PC, sin enviar audio fuera de la máquina;
- modelo local en el ESP32, solo si el consumo de RAM, latencia, idioma y
  precisión son aceptables;
- transporte cifrado de audio a un único consumidor local, con consentimiento,
  borrado y límites explícitos.

No se elegirá una opción por conveniencia de implementación. La decisión debe
incluir idioma, latencia, consumo, exposición de datos, recuperación ante
desconexión y comportamiento cuando el usuario revoca el permiso.

## Orden de implementación cuando llegue la placa

1. Fotografiar/leer la revisión y guardar solo el dato de revisión, nunca una
   foto con información personal en Git.
2. Ejecutar pantalla, touch, I²C y batería por separado.
3. Confirmar las direcciones y respuestas de ES8311/ES7210 sin activar PA_CTRL.
4. Compilar y, con la placa presente, inicializar clocks e I²S en la rama
   opt-in `audio-i2s-lab`, que no anuncia audio al Core.
5. Medir captura y reproducción con buffers acotados, watchdog y cancelación.
6. Añadir el estado visible de escucha y comprobar que el touch cancela.
7. Implementar bloques v2 cifrados y validar los vectores Python/firmware antes
   de transportar una sola muestra real.
8. Añadir STT elegido con pruebas de idioma, permisos, desconexión y borrado.
9. Solo después publicar una capacidad de voz en el catálogo y habilitar
   comandos que puedan producir acciones externas.

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
