# Checklist de llegada del Waveshare

Esta lista valida primero hardware y transporte. No habilita Trusted Unlock ni
elimina contraseña, PIN o Windows Hello.

## 1. Identificación física

- Confirma que la placa es la variante `ESP32-S3-Touch-LCD-1.85C-BOX` (SKU
  30684).
- La documentación oficial indica que la V1 está discontinuada y se sustituye
  por V2 desde el 30 de enero de 2026; aun así, trata el SKU como insuficiente
  y exige una comprobación física antes de elegir el firmware.
- Busca `Rev2.0` en la serigrafía, el firmware de fábrica o la etiqueta `V2`.
- Si no coincide, no flashees: selecciona el entorno V1 únicamente tras revisar
  el pinout oficial.

Antes de tocar la placa, ejecuta desde la raiz:

```powershell
.\scripts\pipa_preflight.ps1 -CheckFirmware
```

Despues de configurar el COM, repite:

```powershell
.\scripts\pipa_preflight.ps1 -CheckFirmware -RequireHardware
```

Ese modo abre el puerto en lectura durante unos segundos y comprueba los
marcadores de arranque de V2. No envia comandos, no activa Wake-on-LAN y no
imprime la clave publica ni el contenido completo del puerto. Para repetir solo
la prueba fisica:

```powershell
python .\windows-agent\pipa_hardware_check.py --port COM7
```

Antes de que llegue la placa, se puede probar el mismo parser con la
transcripcion sintetica incluida en el repositorio. Este modo no abre ningun
puerto, no valida hardware real y no cambia ninguna configuracion:

```powershell
python .\windows-agent\pipa_hardware_check.py `
  --fixture .\windows-agent\tests\fixtures\waveshare-v2-boot.txt --json
```

Para obtener solo una huella comparable, sin imprimir la clave pública:

```powershell
python .\windows-agent\pipa_hardware_check.py --port COM7 --fingerprint
```

Si conectas tarde el USB y te pierdes los primeros mensajes, pulsa reset en la
placa y vuelve a lanzar la prueba. Un resultado correcto exige identidad
publica valida, revision V2, expansor IO, pantalla, touch y ADC de bateria.
La presencia de los codecs de audio se informa tanto en el monitor como en el
resumen de `pipa_hardware_check.py`, pero no bloquea esta prueba porque la
captura y reproduccion siguen deliberadamente desactivadas.

La forma recomendada de preparar el puerto, sin escribir nada todavía, es:

```powershell
.\scripts\prepare_waveshare.ps1 -Port COM7 -WhatIf
```

Cuando esa comprobación sea correcta, repite sin `-WhatIf` y añade
`-RestartAgent` si quieres que el agente oculto se reinicie automáticamente:

```powershell
.\scripts\prepare_waveshare.ps1 -Port COM7 -RestartAgent
```

El script solo guarda `PIPA_SERIAL_PORT` como variable del usuario después de
validar la placa. No carga firmware, no envía comandos al dispositivo, no
configura Wi-Fi y no empareja la clave.

## 2. Configuración local

```powershell
Copy-Item .\firmware\include\pipa_device_config.example.h `
  .\firmware\include\pipa_device_config.local.h
```

Rellena solo el archivo `.local.h` con la red 2,4 GHz, la MAC del PC y el
identificador del dispositivo. Ese archivo está ignorado por Git. Mantén
`PIPA_SECURE_SESSION_ENABLED` en `0` durante la primera validación física.

## 3. Compilación y primera carga

Para una placa V2 confirmada:

```powershell
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c
.\scripts\flash_waveshare.ps1 -Port COM7 -Environment waveshare-185c `
  -AllowDevelopmentFirmware -WhatIf
.\scripts\flash_waveshare.ps1 -Port COM7 -Environment waveshare-185c `
  -AllowDevelopmentFirmware
```

El segundo comando vuelve a sondar la placa, recompila y solicita confirmacion
de PowerShell antes de flashear. No uses este cargador con las variantes
`secure-session-vector`, `secure-session-v2` o `audio-i2s-lab`; son entornos de
prueba y no se consideran firmware de uso diario.

Antes de escribir, el cargador ejecuta una lectura eFuse filtrada y solo de
lectura. Comprueba `SPI_BOOT_CRYPT_CNT`, `SECURE_BOOT_EN` y `SECURE_VERSION`;
si cualquiera indica cifrado de Flash, Secure Boot o anti-rollback, aborta.
Esto protege una placa ya asegurada contra una imagen plaintext de desarrollo.
La imagen actual sigue sin ser una release segura; no se deben quemar eFuses
ni activar esas protecciones hasta tener preparado el flujo de producción,
firmado y recuperación.

La compilación V1 de compatibilidad solo sirve para comprobar el mapa:

```powershell
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c-v1
```

## 4. Comprobaciones físicas

Abre el monitor y conserva únicamente logs revisados:

```powershell
.\firmware\.venv\Scripts\pio.exe device monitor -d firmware -b 115200
```

Debes comprobar, sin publicar la salida completa:

- aparece `PIPA_PUBLIC_KEY=...`;
- la pantalla inicializa sin errores y el touch responde;
- Wi-Fi solo conecta si configuraste explícitamente la red;
- Wake-on-LAN despierta el PC, pero nunca se interpreta como autenticación;
- si hay batería conectada, `device_status` informa un porcentaje aproximado sin
  controlar la carga;
- la sonda de audio no enciende el amplificador ni captura audio;
- una desconexión USB provoca reintento y no deja una sesión autorizada vieja.

## 5. Fingerprint y emparejamiento

Obtén la clave pública por USB, calcula su fingerprint sin tocar el Registro y
compárala físicamente:

```powershell
.\windows-agent\.venv\Scripts\python.exe .\windows-agent\trusted_unlock_admin.py fingerprint `
  --public-key <CLAVE_PUBLICA_BASE64URL>
```

Solo si coincide:

```powershell
.\windows-agent\.venv\Scripts\python.exe .\windows-agent\trusted_unlock_admin.py pair `
  --device-id waveshare-01 `
  --public-key <CLAVE_PUBLICA_BASE64URL> `
  --expected-fingerprint <FINGERPRINT_COMPARADO>
```

El comando rechaza la operacion antes de escribir el Registro si la huella no
coincide exactamente con la clave proporcionada.

Después configura el puerto COM y reinicia el agente. Comprueba que
`/pipa/protocol` informa `serial_gateway_running=true` y
`serial_gateway_connected=true`; un hilo que solo reintenta abrir el puerto no
cuenta como conexión. Comprueba también que una acción externa requiere
pantalla, touch y una confirmación visible.

## 6. Activación posterior de sesión segura

Solo después de que v1 funcione de extremo a extremo:

1. ejecuta `python .\windows-agent\pipa_cli.py secure-test`;
2. provisiona en la configuración local del firmware el `server_id` y la clave
   pública del agente obtenidos con
   `python .\windows-agent\secure_identity_admin.py firmware-snippet`, y
   compáralos por un canal local, nunca desde el propio USB;
3. establece `PIPA_SECURE_SESSION_ENABLED` a `1` y
   `PIPA_SERIAL_SECURITY=v2` en Windows;
4. vuelve a ejecutar el preflight y comprueba que una línea v1 no es aceptada
   por el gateway v2.

Si falta la clave, DPAPI o un dispositivo emparejado, el gateway v2 se queda
desactivado y no degrada a v1.

## 7. No avanzar todavía

No habilites desbloqueo de Windows, voz remota, OTA ni transporte móvil hasta
validar Secure Boot, cifrado de Flash, recuperación, actualización firmada y
un modelo de amenazas independiente.
