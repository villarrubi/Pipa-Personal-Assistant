# Firmware de Pipα para Waveshare ESP32-S3-Touch-LCD-1.85C

Esta carpeta contiene el firmware específico para el modelo comprado:
**ESP32-S3-Touch-LCD-1.85C-BOX, SKU 30684**.

La placa aporta Wi‑Fi 2,4 GHz, BLE 5, pantalla táctil circular, micrófono,
audio y USB-C. La documentación y el mapa de pines oficiales están en
[Waveshare](https://docs.waveshare.com/ESP32-S3-Touch-LCD-1.85C).

## Qué está implementado

- Identidad Ed25519 generada en el propio dispositivo y guardada en NVS.
- Petición de desafío y respuesta firmada por USB CDC.
- Transporte JSON delimitado por líneas, compatible con `pipa_core`.
- Wake-on-LAN local al tocar la pantalla.
- Lectura básica del controlador táctil CST816.
- Reintento de autenticación si Windows todavía no tiene el agente listo.
- Configuración local separada de Git.

El firmware no contiene contraseñas, tokens ni claves privadas del repositorio.
La clave privada se genera en el dispositivo en el primer arranque. La clave
pública aparece una sola vez por el monitor serie para poder emparejarla con
la CLI administrativa de Windows.

Durante desarrollo la clave se guarda en NVS. Antes de considerar el
desbloqueo apto para uso real hay que activar y verificar el cifrado de Flash
y Secure Boot del ESP32-S3; hasta entonces el firmware solo debe usarse para
pruebas de conexión, pantalla y Wake-on-LAN.

## Preparación

Se recomienda PlatformIO con Arduino-ESP32. Waveshare también ofrece ejemplos
oficiales para Arduino y ESP-IDF; esta primera integración usa Arduino para
mantener el transporte y las pruebas sencillos mientras no tenemos la placa.

```powershell
Copy-Item .\firmware\include\pipa_device_config.example.h `
  .\firmware\include\pipa_device_config.local.h
```

Edita únicamente `pipa_device_config.local.h`:

```cpp
#define PIPA_WIFI_SSID "tu-wifi-2.4GHz"
#define PIPA_WIFI_PASSWORD "tu-clave"
#define PIPA_PC_MAC "AA:BB:CC:DD:EE:FF"
#define PIPA_DEVICE_ID "waveshare-01"
```

Ese archivo está ignorado por Git.

## Compilar y cargar

Con PlatformIO instalado:

```powershell
pio run -d firmware
pio run -d firmware -t upload
pio device monitor -d firmware
```

El entorno usa un `esp32-s3-devkitc-1` como base, 16 MB de Flash y USB CDC.
El mapa real de pantalla/audio puede variar entre V1 y V2; la revisión se
selecciona con `PIPA_BOARD_REVISION` y se comprobará con la placa física.

## Emparejamiento

1. Abre el monitor serie a 115200 baudios.
2. Copia el valor `PIPA_PUBLIC_KEY=...` que muestra el dispositivo.
3. En una consola elevada del agente ejecuta:

```powershell
python .\windows-agent\trusted_unlock_admin.py pair `
  --device-id waveshare-01 `
  --public-key CLAVE_PUBLICA_BASE64URL
```

4. Configura el puerto USB del dispositivo para el agente:

```powershell
$env:PIPA_SERIAL_PORT = "COM7"
python .\windows-agent\main.py
```

En la instalación automática, esa variable debe formar parte de la
configuración del usuario que ejecuta la tarea. El gateway serie está
desactivado si `PIPA_SERIAL_PORT` no está definido.

## Seguridad

- El gateway serie no abre ningún puerto de red.
- El desafío caduca y solo puede consumirse una vez.
- La clave privada nunca se envía por USB ni por Wi‑Fi.
- El almacenamiento NVS sin cifrado de Flash no se considera una protección
  suficiente para desbloquear Windows.
- El dispositivo no puede ejecutar una herramienta peligrosa sin la
  confirmación prevista por el protocolo.
- El firmware actual todavía no produce una serialización de Windows ni
  habilita el desbloqueo automático. Esa será una fase posterior, después de
  probar emparejamiento, reinicios, pérdida de conexión y recuperación.

## Sin hardware

La parte Python se puede probar sin la placa:

```powershell
python -m unittest discover -s backend/tests -p "test_*.py"
python -m unittest discover -s windows-agent/tests -p "test_*.py"
```

La compilación y la validación de pantalla, micrófono, altavoz y Wake-on-LAN
requieren conectar el Waveshare real.
