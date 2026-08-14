# Pipα — asistente personal local

Pipα es un asistente para Windows con un agente local, un núcleo de comandos
confirmables y firmware para el **Waveshare ESP32-S3-Touch-LCD-1.85C-BOX
(SKU 30684)**. El diseño prioriza funcionamiento local, permisos mínimos y
recuperación segura.

## Estado real

| Componente | Estado |
| --- | --- |
| Windows Agent | Operativo en `127.0.0.1:8765`, con lanzador oculto preparado y log local rotativo |
| Comandos de PC | Operativos: apps, web, música, audio, multimedia, temporizadores, League, WhatsApp y Discord |
| Núcleo Pipα | Operativo: sesiones, Ed25519, estados de UI, herramientas y confirmaciones |
| Gateway Waveshare | Implementado por USB CDC; requiere configurar el futuro puerto COM |
| Firmware SKU 30684 | Compila para ESP32-S3 N16R8; aún no se ha probado en la placa física |
| Pinout del firmware | Preparado para V2; touch con TCA9554 y confirmación por toque |
| Pantalla | Driver QSPI ST77916 y UI mínima integrados; falta validación física |
| Micrófono y altavoz | Sonda segura ES8311/ES7210 integrada; I²S y voz pendientes |
| Voz Waveshare | El protocolo acepta texto reconocido; el firmware aún no tiene STT y el cierre de audio falla de forma explícita y segura |
| Voz iPhone | Dictado local opcional que solo prepara el texto; requiere compilar y probar en Xcode |
| Wake-on-LAN | Paquete puro en firmware e iPhone; falta probar el broadcast y configurar BIOS/red |
| Trusted Unlock | **Desactivado**: la tile existe, pero no autentica ni entrega credenciales a Windows |
| iPhone/remoto | Proyecto Xcode, núcleo Swift CryptoKit/Keychain, TCP v2 y UI SwiftUI preparados; búsqueda web, Wake-on-LAN y Apple Music locales incluidos; falta probar el iPhone real |

Pipα no sustituye ni desactiva contraseña, PIN, Windows Hello u otros
Credential Providers. Hoy no permite entrar en Windows sin uno de esos métodos.

## Arquitectura

```text
Waveshare --USB JSON + firma Ed25519--> Gateway serie
                                               |
iPhone futuro --PipaMobileCore + TCP v2 opt-in--> Pipα Core --> herramientas Windows
                                               |                 |
                                               |                 +--> confirmación si sale del PC
                                               +--> sesión temporal

Credential Provider --> broker local experimental --> siempre unlock_enabled=false
```

El agente HTTP y WebSocket solo escucha en loopback. El transporte móvil TCP
v2 también está desactivado por defecto y solo acepta una IP privada concreta
cuando se configura explícitamente. El dispositivo se autentica mediante
identidades Ed25519 emparejadas; las acciones externas se ligan a la sesión
que las solicitó y caducan si no se confirman.

## Qué puedes usar sin hardware

- Abrir aplicaciones configuradas localmente y bloquear el PC.
- Abrir Codex o una aplicación configurada mediante una frase confirmable, sin
  escribir nada en chats.
- Buscar en Internet, abrir Apple Music y abrir búsquedas musicales; después
  de elegir una pista, controlar reproducción/pausa, anterior, siguiente o
  parada con el reproductor activo (`music-play`, `music-next`,
  `music-previous`, `music-stop`).
- Controlar volumen y teclas multimedia.
- Crear y consultar temporizadores en memoria.
- Abrir una URL validada desde una frase, siempre con confirmación.
- Abrir League y comenzar/cancelar matchmaking en colas permitidas; una
  búsqueda confirmada puede abrir el cliente si todavía no está listo.
- El estado de League se reduce a datos seguros y la búsqueda falla cerrada si
  el cliente devuelve un estado de matchmaking desconocido. Si ya hay una
  partida encontrada, se avisa sin aceptarla ni rechazarla; ambos pasos siguen
  siendo manuales.
- Abrir WhatsApp Web, abrir el chat de un alias o de un teléfono, o preparar un
  mensaje sin pulsar `Enviar`.
- Si existe una entrada local allowlisted `whatsapp`, abrir esa app; en caso
  contrario, usar el fallback web sin cambiar el límite de Enviar manual.
- Consultar si las integraciones y los alias locales están configurados con
  `python .\windows-agent\pipa_cli.py integration-status`.
- Usar alias locales ignorados por Git para preparar WhatsApp sin dictar el
  teléfono.
- Abrir Discord o un canal sin iniciar automáticamente una llamada.
- Si existe una entrada local allowlisted `discord`, abrir esa app; en caso
  contrario, usar el fallback web sin iniciar llamadas.
- Usar alias locales de Discord para abrir un canal sin iniciar la llamada.
- Pedir una llamada de Discord para un alias: abre el destino y deja el botón
  `Llamar` para la persona.
- Pedir una llamada de Discord por ID de canal validado: abre el destino y
  deja el botón `Llamar` para la persona.
- Consultar el estado de matchmaking de League y evitar duplicar una búsqueda.
- Avisar cuando League encuentra una partida, dejando la aceptación al usuario.
- Consultar por separado el estado de búsqueda de League, la batería/red del
  PC y listar o cancelar temporizadores locales.
- Probar las integraciones desde `windows-agent/pipa_cli.py` sin tener el
  Waveshare conectado.
- Dictar un comando en el iPhone y revisarlo en el editor antes de enviarlo;
  no depende todavía del hardware Waveshare.
- Desde el iPhone, abrir un chat de WhatsApp con un mensaje preparado o un
  canal de Discord mediante enlaces HTTPS; el envío y la llamada siguen siendo
  manuales y esos datos no se guardan.
- En las confirmaciones del iPhone se puede revisar también una copia efímera
  del comando recién preparado; no viaja en `confirm_request`, no se persiste y
  una discrepancia entre la herramienta elegida y la solicitada bloquea la
  aceptación.
- Desde el iPhone, abrir una búsqueda web local en Safari tras una confirmación
  visible; la consulta no pasa por el agente ni se almacena.
- Desde el iPhone, despertar el PC con Wake-on-LAN tras una confirmación visible:
  la MAC se valida localmente, el paquete va al broadcast UDP de la red local y
  no pasa por el agente ni se guarda.
- El parser también entiende frases naturales como `quiero buscar una partida
  en el LoL` y `manda un mensaje a ... por WhatsApp`; siguen pasando por la
  misma confirmación y nunca envían por sí solas.
- Ejecutar `python .\windows-agent\pipa_cli.py doctor` para comprobar en una
  sola operación la salud local, capacidades, protocolo e integraciones.
- Ejecutar `powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File
  .\scripts\check_pre_hardware.ps1` para pasar la compuerta previa al
  hardware. Solo ejecuta pruebas inertes de protocolo, seguridad, móvil y
  configuración, incluida la política de logs: no abre aplicaciones, no
  envía mensajes y no toca League.
  En CI o en un PC sin agente residente puede añadirse `-SkipResidentAgent`.
- Ejecutar `python .\windows-agent\pipa_cli.py self-test` para validar la
  configuración de aplicaciones, URLs, rutas de voz, colas de League y
  gateway sin abrir aplicaciones ni contactar con League Client; incluye un
  simulador v1 y un loopback serie v2 inertes con handshake, catálogo,
  confirmación, rechazo sin touch y redacción.
- Ejecutar `python .\windows-agent\pipa_cli.py local-self-test` para ejecutar
  esas comprobaciones directamente desde el código actual del repositorio,
  sin consultar al proceso residente. Es la opción adecuada justo después de
  actualizar el código, porque `self-test` puede reflejar un agente que aún no
  se haya recargado.
- Ejecutar `python .\windows-agent\pipa_cli.py local-capabilities` para ver la
  matriz completa que usaría la siguiente recarga del agente, sin depender del
  proceso residente ni exponer contactos, teléfonos, IDs, URLs o tokens.
- Ejecutar `python .\windows-agent\pipa_cli.py secure-test` para comprobar en
  memoria el handshake autenticado, el cifrado y el rechazo de manipulación
  del protocolo v2, sin hardware, red ni claves persistentes.
- Ejecutar `python .\windows-agent\pipa_cli.py secure-audio-test` para
  comprobar el contrato de audio cifrado con PCM sintético, consentimiento,
  orden y límites, sin activar micrófono, red, puerto serie ni claves
  persistentes.
- Ejecutar `python .\windows-agent\pipa_cli.py integration-test` para validar
  los constructores de búsqueda/WhatsApp/Discord, las colas de League y los
  límites de selección, envío, llamada y aceptación; no abre aplicaciones ni
  contacta con servicios externos.
- Ejecutar `python .\windows-agent\pipa_cli.py mobile-test` para validar en
  memoria el flujo futuro de iPhone: handshake, capacidades de pantalla/touch,
  confirmación y resultado sin datos privados.
- Ejecutar `python .\windows-agent\pipa_cli.py mobile-tcp-test` para validar
  el transporte cifrado real sobre un puerto efímero de `127.0.0.1`.
- Ejecutar `python .\windows-agent\pipa_cli.py mobile-config` para validar la
  configuración móvil sin abrir puertos, modificar el firewall ni modificar claves;
  también valida que la identidad DPAPI corresponda al `server_id` configurado.
  Si el transporte está activado, comprueba además que la IP privada configurada
  esté asignada realmente a este PC; una dirección privada de otro equipo se
  rechaza antes de reiniciar el agente.
- Preparar, solo cuando llegue el iPhone, una regla de firewall restringida con
  `scripts/configure_mobile_firewall.ps1 -WhatIf` antes de aplicarla.
- Preparar la configuración de transporte móvil sin escribirla a mano con
  `scripts/configure_mobile_transport.ps1 -LocalAddress <IP_PRIVADA> -WhatIf`;
  el script valida la IP y solo modifica variables de usuario cuando se ejecuta
  sin `-WhatIf`.
- Preparar la identidad pública del agente v2 sin exponer la clave privada:
  `python .\windows-agent\secure_identity_admin.py init` y después
  `firmware-snippet` cuando se vaya a provisionar la placa.
- Consultar la matriz local de capacidades con
  `python .\windows-agent\pipa_cli.py capabilities`.
- Consultar el catálogo de frases y sus confirmaciones con
  `python .\windows-agent\pipa_cli.py commands`.
- Inspeccionar cómo se interpreta una frase con `pipa_cli.py intent` sin
  ejecutar ninguna acción.
- Revisar con `pipa_cli.py preview` la herramienta, argumentos y confirmación
  que tendría una frase, sin abrir aplicaciones ni tocar League; también
  indica si los argumentos y la configuración local están listos, por ejemplo
  si existe el alias de WhatsApp o Discord.
- Ejecutar desde la CLI una acción externa solo con `--confirm`; las consultas
  de estado siguen siendo de solo lectura.
- Probar todo el protocolo de dispositivo con un simulador efímero.
- Recorrer las cinco integraciones desde un simulador autenticado con
  `python .\windows-agent\pipa_cli.py integration-protocol-test`; usa handlers
  sintéticos, exige confirmación y no abre aplicaciones ni contacta servicios.
- El contrato de audio cifrado ya tiene un consumidor por chunks en Windows:
  exige codec listo, indicador visible, consentimiento y transporte seguro;
  entrega memoria efímera a un futuro STT local, borra el buffer y cierra la
  sesión ante errores o streams truncados. `SecureAudioTranscriber` valida el
  transcript final antes de pasarlo al parser; `PipaCore.handle_transcript`
  mantiene una segunda validación y la misma compuerta de confirmación que el
  texto móvil. El diagnóstico usa un proveedor sintético y todavía no captura
  ni anuncia voz real.
- Compilar el firmware exacto sin tener la placa.
- La app iPhone recuerda la configuración pública de conexión en Keychain y
  permite completar en un formulario local los parámetros de búsquedas,
  WhatsApp, Discord o League antes de preparar la frase, sin enviarla
  automáticamente.
- Cuando el agente publica metadatos tipados, ese formulario también puede
  enviar un `tool_call` estructurado cifrado: valida localmente teléfonos,
  mensajes, enteros, colas y opciones sin depender del parser de frases.
- Al conectar, la app iPhone muestra también qué integraciones están
  disponibles en el PC y qué paso manual queda pendiente; esa matriz no
  contiene rutas, URLs, contactos, IDs ni tokens.

El gateway serie v2 cifrado también está preparado, pero permanece opt-in:
`PIPA_SERIAL_SECURITY=v2` no hace downgrade a v1 si el handshake falla. Hasta
validar la placa y provisionar la clave pública del agente en el firmware, el
valor recomendado sigue siendo el transporte v1 local ya probado.

Consulta el catálogo y sus límites en
[windows-agent/README.md](windows-agent/README.md).
El contrato del futuro cliente móvil está en
[MOBILE_PROTOCOL.md](MOBILE_PROTOCOL.md).
El núcleo Swift para iOS está en
[mobile-ios/README.md](mobile-ios/README.md).
La validación cuando haya Mac/iPhone está enumerada en
[mobile-ios/ARRIVAL_CHECKLIST.md](mobile-ios/ARRIVAL_CHECKLIST.md).
El diseño previo a hardware de audio y voz está en
[firmware/AUDIO_STT_DESIGN.md](firmware/AUDIO_STT_DESIGN.md).
El contrato binario cifrado que se validará antes de conectar la captura está
en [SECURE_AUDIO_PROTOCOL.md](SECURE_AUDIO_PROTOCOL.md).

Por ejemplo, el Core ya entiende frases como `abre WhatsApp`, `abre WhatsApp
para mama`, `abre Discord`, `abre Codex`, `abre una aplicación configurada
calculadora`, `abre Apple Music`, `busca en Apple Music Daft Punk`, `busca
una canción de Daft Punk en Apple Music`, `pon una canción de Daft Punk en Apple Music`,
`busca partida`, `busca partida solo`,
`control multimedia next`, `busca la canción de Daft Punk en Apple Music` y,
después de elegirla, `reproduce la canción seleccionada`, además de preparar un
mensaje de WhatsApp sin enviarlo —por ejemplo `abre WhatsApp con mama y escribe
Hola`—, consultar el estado de League y cancelar una búsqueda con confirmación.
También entiende variantes naturales como `cancela la búsqueda del LoL` y
`llama por Discord a amigo`; ambas conservan la confirmación y el último paso
manual correspondiente.
También acepta formas equivalentes como `busca una partida de LoL`, `manda un
mensaje de WhatsApp a mamá diciendo llego` y `haz una llamada de Discord con
amigo`; el parser solo cambia la forma de la petición, no la política de
confirmación ni los pasos manuales.
Desde una sesión autenticada, las acciones externas requieren confirmación y las
interfaces que puedan enviar o llamar siguen requiriendo la acción final del
usuario. Tras seleccionar una canción, el catálogo móvil ofrece reproducir/pausar
y pasar de pista mediante el reproductor multimedia activo; no selecciona una
pista ni garantiza que Apple Music sea el reproductor que tenga el foco. La
sección local del iPhone también permite anterior y detener mediante MusicKit.

En Discord, el catálogo móvil también permite rellenar un servidor y un canal
por separado con `abre Discord servidor <servidor> canal <canal>`; el agente
valida ambos IDs antes de abrir el destino y no inicia la llamada.

En Apple Music remoto la búsqueda no selecciona ni inicia una pista
automáticamente. Después de elegirla, `reproduce la canción seleccionada`,
`reanuda la pista` y `pausa la canción` controlan el reproductor multimedia
activo mediante una tecla de Windows; si otra aplicación es el reproductor
activo, esa aplicación recibirá la orden. La app iOS ofrece además una sección
local opcional con MusicKit para buscar y reproducir directamente en el iPhone,
con permiso explícito del sistema y sin enviar la consulta al agente.

## Instalación del agente

Desde PowerShell en la raíz:

```powershell
python -m venv .\windows-agent\.venv
.\windows-agent\.venv\Scripts\python.exe -m pip install `
  -r .\windows-agent\requirements.txt
```

Inícialo manualmente y comprueba el estado:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\start_agent_hidden.ps1

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\check_agent_status.ps1
```

Para arrancarlo al iniciar sesión, ejecuta una vez PowerShell normal (la tarea
se registra para tu usuario y con nivel limitado):

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\install_agent_task.ps1
```

Para instalar sin pregunta interactiva, usa una política temporal de proceso:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\windows-agent\install_agent_task.ps1 -Confirm:$false
```

El agente no deja una ventana CMD abierta. Si el Programador de tareas está
restringido, el instalador usa `HKCU` o un acceso directo `.lnk` en `Startup`
como fallback. Su log está en
`%LOCALAPPDATA%\Pipa\logs\agent.log`, rota a 1 MB y conserva dos copias.
`check_agent_status.ps1` también verifica que la tarea use PowerShell oculto,
arranque al iniciar sesión y nivel limitado, y que ejecuta exactamente el
lanzador de Pipa con el usuario correcto; una tarea arbitraria de PowerShell no
se considera válida. Al actualizar la instalación, el lanzador recarga el
agente mediante una señal local de apagado dirigida al propio servidor; solo
usa la comprobación exacta de proceso como fallback y nunca mata un PID ajeno
solo porque escuche en el puerto 8765.

## Validación

Activa una vez los hooks locales de seguridad de este repositorio:

```powershell
git config core.hooksPath .githooks
```

Desde entonces, cada commit revisa los archivos publicables y cada push vuelve
a revisar tanto esos archivos como todo el historial alcanzable.

```powershell
python -B -m unittest discover -s backend/tests -p "test_*.py"
python -B -m unittest discover -s windows-agent/tests -p "test_*.py"
python -m compileall -q backend windows-agent scripts

.\scripts\check_repo_hygiene.ps1
.\scripts\check_git_history.ps1
.\scripts\check_powershell_syntax.ps1
.\scripts\check_trusted_unlock_safety.ps1

# Comprobacion unificada del estado local. Incluye el checkout actual y el
# agente residente para no confundir código actualizado con un proceso antiguo.
.\scripts\pipa_preflight.ps1
```

La CI repite esas comprobaciones, ejecuta Ruff, audita dependencias, compila
el firmware y construye/prueba el Credential Provider x64.

La comprobación de higiene también prueba con rutas ficticias que `.gitignore`
cubre configuraciones locales, claves, builds, logs, capturas, grabaciones y
trazas antes de permitir publicar el árbol.

Para compilar el firmware:

```powershell
python -m venv .\firmware\.venv
.\firmware\.venv\Scripts\python.exe -m pip install platformio==6.1.19
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c
```

El preflight no modifica configuraciones. Con `-CheckFirmware` añade todas las
compilaciones del firmware; con `-RequireHardware` convierte la ausencia de
`PIPA_SERIAL_PORT` en un fallo, útil después de conectar el Waveshare.
Para las comprobaciones Python usa primero `windows-agent/.venv` si existe y
solo recurre al `python` del `PATH` cuando no hay ese entorno local.

Si el resultado muestra `Programador inaccesible` pero el agente aparece como
`online`, el proceso está funcionando y el único dato no verificado es la tarea
de inicio. Ejecuta el diagnóstico desde una PowerShell con permisos suficientes
para consultar el Programador de tareas; no desactives la comprobación ni
instales una tarea con privilegios elevados para ocultar ese aviso.

Para ejecutar el resto del preflight mientras estás en una sesión sin acceso al
Programador, puedes usar `./scripts/pipa_preflight.ps1 -SkipStartupCheck`.
Ese modo deja un aviso explícito y no sustituye la verificación posterior del
arranque.

## Cuando llegue el Waveshare

La secuencia operativa detallada está en
[firmware/ARRIVAL_CHECKLIST.md](firmware/ARRIVAL_CHECKLIST.md).

La primera preparación recomendada valida el USB en modo pasivo antes de
guardar ningún puerto ni reiniciar el agente:

```powershell
.\scripts\prepare_waveshare.ps1 -Port COM7 -WhatIf
```

Si el informe confirma la placa esperada, se puede guardar el COM solo para el
usuario y reiniciar el agente oculto en una segunda operación:

```powershell
.\scripts\prepare_waveshare.ps1 -Port COM7 -RestartAgent
```

Este flujo no carga firmware, no configura Wi-Fi, no empareja claves y no
activa la sesión segura v2. Es intencionadamente una compuerta previa; el
emparejamiento debe hacerse después comparando el fingerprint de la clave por
un canal físico.

Cuando la placa ya haya sido validada, usa `scripts/flash_waveshare.ps1` para
compilar y cargar únicamente el entorno de desarrollo correspondiente a la
revisión V1/V2. El script bloquea las variantes experimentales y exige
`-AllowDevelopmentFirmware`, además de pedir confirmación antes de escribir en
el dispositivo. La imagen actual no tiene todavía Secure Boot ni cifrado de
Flash, por lo que no se puede tratar como firmware de producción.
Antes de la escritura, el cargador lee de forma filtrada el estado eFuse y
aborta si la placa ya está protegida; así no se intenta cargar plaintext sobre
un dispositivo con Secure Boot, cifrado de Flash o anti-rollback.

Solo quedará trabajo dependiente del dispositivo:

1. confirmar revisión de placa, pines y controladores de pantalla/audio;
2. cargar el firmware y comprobar USB, touch, Wi‑Fi y Wake-on-LAN;
3. comparar físicamente la huella de la clave antes de emparejarla;
4. validar la UI QSPI y después implementar captura de audio y STT para español sobre un transporte protegido;
5. validar Secure Boot, cifrado de Flash, actualización y recuperación;
6. revisar de nuevo el modelo de amenazas antes de plantear desbloqueo real.

## Seguridad y privacidad

Las configuraciones con rutas, Wi‑Fi, MAC o puertos viven en archivos locales
ignorados. No deben entrar en Git claves privadas, tokens, builds, logs,
capturas de LogonUI ni datos personales. Los controles y limitaciones están
documentados en [SECURITY.md](SECURITY.md).

La biblioteca offline ESP-SR que trae Arduino-ESP32 ofrece reconocimiento de
comandos en chino e inglés, no un STT general en español. Por eso el firmware
no finge reconocer frases españolas: el siguiente diseño debe usar un
reconocedor español en Windows o un servicio explícitamente autorizado, con
audio protegido y un indicador visible de escucha. Referencias: [guía oficial
de ESP-SR](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/speech_command_recognition/README.html)
y [repositorio oficial](https://github.com/espressif/esp-sr).

## Estructura

```text
Pipa/
├── backend/          protocolo, sesiones, memoria temporal y simulador
├── firmware/         firmware PlatformIO y definición de la placa N16R8
├── mobile-ios/       núcleo, UI SwiftUI y plantilla de app iPhone
├── scripts/          comprobaciones de higiene actual e histórica
├── MOBILE_PROTOCOL.md contrato del futuro cliente iPhone
├── trusted-unlock/   Credential Provider experimental y rollback
└── windows-agent/    API local, herramientas, gateway USB y arranque oculto
```
