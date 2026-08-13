# Firmware Pipα — Waveshare ESP32-S3-Touch-LCD-1.85C

Firmware específico para el **ESP32-S3-Touch-LCD-1.85C-BOX, SKU 30684,
N16R8**. Usa PlatformIO, Arduino-ESP32, 16 MB de Flash, 8 MB de PSRAM y USB
CDC. La referencia física está en la
[documentación oficial de Waveshare](https://docs.waveshare.com/ESP32-S3-Touch-LCD-1.85C).

## Implementado y compilado

- Definición PlatformIO propia para la variante N16R8.
- Identidad Ed25519 generada en el dispositivo y persistida en NVS.
- Fallo cerrado si la identidad NVS existe pero está corrupta.
- Desafío/respuesta firmado y JSON por líneas sobre USB CDC.
- Diagnósticos separados del protocolo mediante líneas que empiezan por `#`.
- Reconexión tras reinicio del agente y timeout de heartbeat.
- Límites de tamaño de mensaje y validación estricta de desafíos.
- Límite común de 12.000 bytes también para mensajes salientes; el texto
  reconocido se rechaza por encima de 4.000 bytes antes de tocar USB.
- Lectura básica del controlador táctil CST816.
- Wake-on-LAN con MAC estricta, cooldown y Wi‑Fi no bloqueante.
- Heartbeat y telemetría de RSSI.
- Mapa de pines separado por revisión V1/V2; la V2 usa I²C en GPIO10/11 y
  reserva el audio para ES8311/ES7210.
- Driver ST77916 basado en la referencia oficial, adaptado a `esp_lcd` moderno,
  con transporte QSPI, retroiluminación PWM y una UI mínima de
  estados/confirmación; queda validar la pantalla en la placa física.
- Diagnóstico I²C no destructivo de ES8311 (salida) y ES7210 (entrada), con el
  amplificador apagado por defecto; la captura/reproducción real aún queda
  pendiente.
- Máquina de estados de audio independiente (`DISABLED` → `PROBE_ONLY` →
  `CODEC_READY` → `LISTENING` → `DRAINING`) con cierre `ERROR`; exige codec
  inicializado, indicador visible, consentimiento y transporte seguro antes de
  permitir una futura escucha. Su vector se ejecuta solo en
  `secure-session-vector` y no captura muestras.
- Entorno opt-in `audio-i2s-lab` que compila la configuración I²S V2 de
  Waveshare sin conectarla al `main`, sin codec, sin muestras y con el
  amplificador forzado a apagado; sirve para detectar cambios del SDK antes de
  tener la placa.
- Telemetría opcional de batería para la revisión V2 mediante el ADC documentado;
  publica solo un porcentaje acotado y no controla carga ni alimentación.
- La pantalla de confirmación muestra el resumen de la acción en ASCII
  normalizado y `TAP`; el protocolo descarta UTF-8 malformado, controles C0/C1
  y formato bidireccional o invisible antes de mostrarlo. El toque no confirma
  una acción cuyo resumen no haya llegado al dispositivo.
- Tras una acción, la pantalla muestra un resultado breve y fijo, sin URLs,
  teléfonos, consultas ni mensajes privados.
- La UI redibuja también cuando cambia el texto de estado, y no sustituye una
  confirmación visible por otra hasta resolverla o cancelarla.
- El `hello` anuncia solo las capacidades físicas que realmente inicializaron
  (`display`, `touch` y `audio_probe`), para que el agente no confunda una
  compilación correcta con hardware disponible.
- Las acciones externas solo se autorizan cuando el Core recibe `display` y
  `touch`; una unidad parcialmente inicializada puede seguir enviando estado,
  pero no puede confirmar acciones.
- Transporte seguro v2 opt-in disponible en `pipa_secure_protocol.cpp`: cifra
  las líneas de Core con ChaCha20-Poly1305 después de un handshake X25519 y
  nunca vuelve a v1 tras iniciar ese modo. Tras autenticarse anuncia por el
  canal cifrado la versión y las capacidades físicas; sin ese anuncio el Core
  no permite confirmar acciones externas. La configuración rastreada lo deja
  desactivado hasta provisionar la clave pública del agente.
- El entorno `secure-session-vector` compila un vector determinista compartido
  con Python para el record layer y el framing de audio v2. El nuevo primitive
  `pipa_secure_audio.h/.cpp` valida límites, secuencias, AAD y cierre
  fail-closed, pero solo se invoca desde ese entorno; su ejecución en una placa
  real sigue pendiente y no forma parte del firmware normal.

La compilación verificada ocupa aproximadamente un 8,0 % de la partición de
aplicación y un 10,2 % de la RAM interna. Es una validación de software; no
demuestra todavía que el pinout, touch, red o periféricos funcionen en la
unidad física.

## Deliberadamente pendiente

- Prueba física de la pantalla, orientación, colores y frecuencia QSPI.
- Micrófono, altavoz, codec/I2S y cancelación de eco. La referencia oficial ya
  está localizada y el firmware solo hace una sonda segura de presencia.
- Reconocimiento de voz local o streaming STT.
- Gestos más ricos que el toque básico.
- Indicador de batería real.
- OTA, partición de recuperación, Secure Boot y cifrado de Flash.

La V2 del 1.85C cambió el audio y varias señales respecto a V1. El firmware
selecciona el mapa con `PIPA_BOARD_REVISION` y registra la revisión al arrancar;
no se debe flashear una configuración V1/V2 sin comprobar la serigrafía o el
firmware de fábrica. La documentación oficial también distingue ambas
revisiones y sus pines, por lo que la pantalla y el audio se validarán en la
unidad física antes de habilitar funciones sensibles. Referencia: [documentación
oficial del 1.85C](https://docs.waveshare.com/ESP32-S3-Touch-LCD-1.85C).

### Mapa de revisión

| Señal | V1 | V2 (esperada en SKU 30684) |
| --- | ---: | ---: |
| Touch SDA / SCL | GPIO1 / GPIO3 | GPIO11 / GPIO10 |
| Touch INT | GPIO4 | GPIO4 |
| Touch/LCD reset | EXIO1 / EXIO2 | EXIO1 / EXIO2 |
| Audio | PCM5101 + micrófono digital | ES8311 + ES7210 + micrófonos analógicos |

La revisión se identifica por `Rev2.0` en la serigrafía o el firmware de
fábrica; también puede aparecer una pegatina `V2`. El SKU 30684 corresponde a la
variante BOX, pero el SKU por sí solo no sustituye la comprobación de revisión.
El [esquema oficial V1/V2 y sus recursos](https://docs.waveshare.com/ESP32-S3-Touch-LCD-1.85C/Resources-And-Documents)
es la referencia para resolver cualquier discrepancia antes de flashear.
El chequeo reproducible en scripts/check_waveshare_pinmap.ps1 mantiene este
mapa protegido contra cambios accidentales y se ejecuta también en el
preflight y la CI.

La capacidad `text_input` significa que el protocolo puede enviar texto ya
reconocido; no significa que el firmware actual escuche voz. Antes de
serializarlo, ambos transportes validan el UTF-8, rechazan controles invisibles
y limitan la fuente del texto; la pantalla
representa el estado recibido y muestra `CONFIRM`/`TAP` cuando hay una acción
pendiente de confirmación.

No se ha activado ESP-SR como solución de voz española: la documentación
oficial de MultiNet limita los modelos disponibles a chino e inglés. La ruta
pendiente es captura I²S y STT español con privacidad, consentimiento e
indicador de escucha, no enviar micrófono en claro por el protocolo actual.
Véase la [documentación oficial de reconocimiento de comandos ESP-SR](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/speech_command_recognition/README.html).

El contrato de la futura implementación de audio, sus estados, límites,
política de borrado y criterios de aceptación está en
[AUDIO_STT_DESIGN.md](AUDIO_STT_DESIGN.md). Hasta validar la placa física, no
se debe añadir una capacidad de audio real ni transportar muestras.

## Configuración local

Copia la plantilla al archivo local ignorado:

```powershell
Copy-Item .\firmware\include\pipa_device_config.example.h `
  .\firmware\include\pipa_device_config.local.h
```

Edita solo `pipa_device_config.local.h`:

```cpp
#define PIPA_WIFI_SSID "tu-wifi-2.4GHz"
#define PIPA_WIFI_PASSWORD "tu-clave"
#define PIPA_PC_MAC "AA:BB:CC:DD:EE:FF"
#define PIPA_DEVICE_ID "waveshare-01"
```

Nunca edites con valores reales el archivo rastreado
`include/pipa_device_config.h`: contiene defaults vacíos para que CI compile
sin secretos.

## Compilar

PlatformIO puede intentar escribir en una caché global con permisos heredados.
Para mantener el toolchain reproducible y dentro del árbol ignorado, define la
caché local antes de compilar desde la raíz del repositorio:

```powershell
$env:PLATFORMIO_CORE_DIR = Join-Path (Get-Location) '.platformio-preflight'
```

Después de terminar, puedes retirar la variable de esta sesión:

```powershell
Remove-Item Env:PLATFORMIO_CORE_DIR -ErrorAction SilentlyContinue
```

La configuración local de PlatformIO no contiene Wi-Fi, MAC ni claves; esos
valores siguen viviendo únicamente en `include/pipa_device_config.local.h`.

```powershell
python -m venv .\firmware\.venv
.\firmware\.venv\Scripts\python.exe -m pip install platformio==6.1.19
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c
```

Para compilar todas las variantes antes de conectar la placa:

```powershell
foreach ($environment in @(
    'waveshare-185c',
    'waveshare-185c-v1',
    'secure-session-vector',
    'secure-session-v2',
    'audio-i2s-lab'
)) {
    .\firmware\.venv\Scripts\pio.exe run -d firmware -e $environment
}
```

`secure-session-vector` y `secure-session-v2` solo comprueban el camino de
sesión segura; no sustituyen el emparejamiento físico ni activan por sí solos
el transporte en una placa.

Para verificar únicamente la compatibilidad con una placa V1 confirmada:

```powershell
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c-v1
```

Ese entorno solo comprueba la compilación del mapa legado; no debe usarse para
flashear el SKU 30684 sin identificar antes la revisión física.

Para compilar la sonda I²S experimental sin habilitarla en el firmware normal:

```powershell
.\firmware\.venv\Scripts\pio.exe run -d firmware -e audio-i2s-lab
```

Este entorno no prueba el micrófono ni el altavoz y no debe flashearse como
firmware de uso diario. La inicialización real de codec, captura y reproducción
sigue bloqueada hasta la validación física. El framing seguro se compila en el
firmware para detectar incompatibilidades, pero no tiene una ruta hacia I²S,
codec, red, serie, pantalla ni almacenamiento.

Para compilar también el entorno explícito del camino seguro:

```powershell
.\firmware\.venv\Scripts\pio.exe run -d firmware -e secure-session-v2
```

Ese build solo comprueba el código. Para activarlo en una placa hay que definir
`PIPA_SECURE_SESSION_ENABLED 1` y provisionar `PIPA_SECURE_SERVER_ID` y
`PIPA_SECURE_SERVER_PUBLIC_KEY` en `pipa_device_config.local.h`, tras verificar
la huella por un canal físico.

La clave pública y los `#define` se pueden obtener sin imprimir la clave privada
con:

```powershell
python .\windows-agent\secure_identity_admin.py init
python .\windows-agent\secure_identity_admin.py firmware-snippet
```

`init` protege la identidad privada con DPAPI en `%LOCALAPPDATA%\Pipa`; el
snippet solo contiene la identidad pública, el fingerprint y la activación
explícita del transporte.

Con la placa conectada:

```powershell
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c -t upload
.\firmware\.venv\Scripts\pio.exe device monitor -d firmware -b 115200
```

## Emparejamiento físico

La secuencia completa de validación está en
[ARRIVAL_CHECKLIST.md](ARRIVAL_CHECKLIST.md).

En cada arranque aparece una línea similar a:

```text
# PIPA_PUBLIC_KEY=<CLAVE_PUBLICA_BASE64URL>
```

La clave pública no es secreta, pero hay que comprobar su fingerprint por un
canal físico antes de autorizarla:

```powershell
.\windows-agent\.venv\Scripts\python.exe `
  .\windows-agent\trusted_unlock_admin.py pair `
  --device-id waveshare-01 `
  --public-key <CLAVE_PUBLICA_BASE64URL> `
  --expected-fingerprint <FINGERPRINT_COMPARADO>
```

Después configura el COM como variable del usuario y vuelve a iniciar sesión:

```powershell
[Environment]::SetEnvironmentVariable('PIPA_SERIAL_PORT', 'COM7', 'User')
```

El gateway se mantiene desactivado si esa variable no existe.

## Comportamiento del touch

- Sin sesión USB autenticada: intenta Wake-on-LAN si Wi‑Fi y MAC están listas.
- Con sesión autenticada: envía un gesto `tap`; si la UI muestra una
  confirmación, el toque confirma únicamente esa acción pendiente.
- Si una confirmación caduca, se rechaza o se cancela, el estado visual vuelve
  a `idle` y el identificador anterior se elimina.
- Wake-on-LAN nunca desbloquea Windows; solo puede encender o despertar un PC
  configurado para aceptarlo.
- El identificador de confirmación se conserva tras transmitir el toque y solo
  se limpia al recibir el resultado o un nuevo estado; así un fallo de
  transporte permite reintentar el mismo toque sin crear otra acción.

## Seguridad antes de uso sensible

La clave privada no sale por USB, pero NVS sin cifrado no basta para un factor
de autenticación de Windows. Antes de habilitar cualquier desbloqueo hay que
provisionar y verificar Secure Boot, cifrado de Flash, anti-rollback,
actualización firmada y recuperación física. Hasta entonces, este firmware es
para comandos, Wake-on-LAN y validación del hardware.
