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
- Lectura básica del controlador táctil CST816.
- Wake-on-LAN con MAC estricta, cooldown y Wi‑Fi no bloqueante.
- Heartbeat y telemetría de RSSI.

La compilación verificada ocupa aproximadamente un 6,2 % de la partición de
aplicación y un 7,9 % de la RAM interna. Es una validación de software; no
demuestra todavía que el pinout, touch, red o periféricos funcionen en la
unidad física.

## Deliberadamente pendiente

- Driver y diseño visual de la pantalla redonda.
- Micrófono, altavoz, codec/I2S y cancelación de eco.
- Reconocimiento de voz local o streaming STT.
- Gestos más ricos que el toque básico.
- Indicador de batería real.
- OTA, partición de recuperación, Secure Boot y cifrado de Flash.

La capacidad `text_input` significa que el protocolo puede enviar texto ya
reconocido; no significa que el firmware actual escuche voz.

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

```powershell
python -m venv .\firmware\.venv
.\firmware\.venv\Scripts\python.exe -m pip install platformio==6.1.19
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c
```

Con la placa conectada:

```powershell
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c -t upload
.\firmware\.venv\Scripts\pio.exe device monitor -d firmware -b 115200
```

## Emparejamiento físico

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
  --public-key <CLAVE_PUBLICA_BASE64URL>
```

Después configura el COM como variable del usuario y vuelve a iniciar sesión:

```powershell
[Environment]::SetEnvironmentVariable('PIPA_SERIAL_PORT', 'COM7', 'User')
```

El gateway se mantiene desactivado si esa variable no existe.

## Comportamiento del touch

- Sin sesión USB autenticada: intenta Wake-on-LAN si Wi‑Fi y MAC están listas.
- Con sesión autenticada: envía un gesto `tap` al Pipα Core.
- Wake-on-LAN nunca desbloquea Windows; solo puede encender o despertar un PC
  configurado para aceptarlo.

## Seguridad antes de uso sensible

La clave privada no sale por USB, pero NVS sin cifrado no basta para un factor
de autenticación de Windows. Antes de habilitar cualquier desbloqueo hay que
provisionar y verificar Secure Boot, cifrado de Flash, anti-rollback,
actualización firmada y recuperación física. Hasta entonces, este firmware es
para comandos, Wake-on-LAN y validación del hardware.
