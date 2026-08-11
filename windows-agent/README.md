# Pipα Windows Agent

Agente local para automatización del PC. En su estado actual ofrece consulta
de estado, apertura de aplicaciones y URLs HTTP/HTTPS, bloqueo del equipo y
control del audio.

El servidor se enlaza a `127.0.0.1:8765`. No debe cambiarse a `0.0.0.0` ni
usarse como broker de Trusted Unlock. El agente vive en la sesión del usuario;
el futuro flujo de LogonUI necesitará un servicio separado y un IPC protegido.

## Configuración

`config/apps.example.json` es la configuración segura para compartir. Para
rutas específicas del ordenador, crea `config/apps.json`; ese archivo está
ignorado por Git.

## Administración de dispositivos

La CLI administrativa guarda solo claves públicas en el Registro x64 de
Windows y requiere una consola elevada para modificarlo:

```powershell
python .\trusted_unlock_admin.py list
python .\trusted_unlock_admin.py pair --device-id phone-main --public-key CLAVE_PUBLICA_BASE64URL
python .\trusted_unlock_admin.py revoke --device-id phone-main --yes
```

La clave privada debe permanecer en el móvil o hardware autorizado.

## Broker local Trusted Unlock

El broker separado (`trusted_unlock_broker.py`) usa el Named Pipe
`\\.\pipe\PipaTrustedUnlock`. Su ACL permite acceso únicamente al usuario que
lo ejecuta y a `SYSTEM`. Acepta salud, desafíos, respuestas firmadas y
tickets de un solo uso; no tiene ningún comando de desbloqueo y anuncia
`unlock_enabled = false`.

Para probarlo manualmente en Windows, instala las dependencias y ejecútalo
desde una consola del agente:

```powershell
python -m pip install -r .\requirements.txt
python .\trusted_unlock_broker.py
```

El emparejamiento y la revocación siguen siendo operaciones administrativas
separadas. Reinicia el broker después de cambiar las claves del Registro.

Esta primera versión no se registra todavía como servicio ni se inicia
automáticamente. El cliente del pipe está preparado para las pruebas del
Credential Provider, pero no existe ninguna ruta que pueda producir una
serialización de Windows.

## Waveshare por USB

El agente incluye un gateway serie opcional para el
`ESP32-S3-Touch-LCD-1.85C-BOX`. No se activa por defecto. Para activarlo,
instala las dependencias y define explícitamente el puerto COM:

```powershell
python -m pip install -r .\requirements.txt
$env:PIPA_SERIAL_PORT = "COM7"
python .\main.py
```

Para que la tarea automática lo herede después de iniciar sesión, guarda el
puerto como variable del usuario y vuelve a iniciar sesión:

```powershell
[Environment]::SetEnvironmentVariable("PIPA_SERIAL_PORT", "COM7", "User")
```

El dispositivo envía `challenge_request`, recibe un desafío efímero, firma el
objeto con su clave Ed25519 y continúa por el mismo protocolo autenticado del
WebSocket. El gateway serie no expone el agente a la red. Para el arranque
automático, la variable debe configurarse en el entorno de la tarea de
Windows, no escribirse en el repositorio.

Las pruebas usan `trusted_unlock_simulator.py`, que genera una identidad
efímera únicamente en memoria. No hay un simulador de producción ni una
clave privada de prueba guardada en el ordenador.

## Inicio sin ventana

Para el inicio automático, configura la tarea existente para ejecutar
PowerShell oculto y `start_agent_hidden.ps1`. El lanzador usa `pyw.exe` o
`pythonw.exe`, por lo que el agente se inicia sin dejar una ventana CMD
visible. Ejecuta PowerShell como administrador (la tarea de Windows requiere
permisos para cambiar su acción):

```powershell
.\install_agent_task.ps1 -WhatIf
.\install_agent_task.ps1
```

`start_agent.bat` se mantiene como lanzador manual y de depuración; ese sí
abre una consola para poder ver los mensajes del agente.

## Comandos de navegador y aplicaciones

Además de `/open-app` y `/open-url`, están disponibles:

```text
POST /web/search       {"query":"..."}
POST /music/search     {"term":"..."}
POST /league/open      {}
POST /codex/open       {}
GET  /league/status
POST /league/search    {"queue":"ranked_solo"}
DELETE /league/search
POST /media/action     {"action":"play_pause"}
GET  /system/power
GET  /system/network
POST /timers           {"seconds":300,"label":"Descanso"}
GET  /timers
DELETE /timers/{id}
POST /whatsapp/compose {"phone":"+34600123456","message":"Hola"}
POST /discord/channel/open {"channel_id":"12345678901234567"}
GET  /pipa/protocol
POST /pipa/challenge   {"device_id":"waveshare-01"}
WS   /pipa/ws
```

Las búsquedas solo abren resultados en el navegador. Apple Music no reproduce
automáticamente una canción; abre su búsqueda web. League puede consultar el
lobby y empezar/cancelar la búsqueda en una cola permitida cuando el cliente ya
está abierto y autenticado. Codex solo se abre si existe una entrada `codex`
explícita en la configuración local ignorada por Git. No se automatiza texto ni
se accede a interfaces de terceros fuera de las rutas locales previstas.

Los comandos multimedia permitidos son `play_pause`, `next`, `previous` y
`stop`. Los temporizadores viven en memoria y se consultan mediante polling;
no persisten tras reiniciar el agente. WhatsApp abre un enlace `wa.me` con el
mensaje preparado, pero siempre requiere pulsar `Enviar` manualmente.
Discord puede abrir un DM, un grupo o un canal de servidor con un ID de
Discord válido. La llamada no se inicia automáticamente: el usuario debe
confirmarla en Discord. No se automatizan cuentas personales ni se leen
contactos, mensajes o tokens.

El WebSocket `/pipa/ws` usa el mismo desafío/respuesta Ed25519 del Trusted
Unlock. El primer mensaje debe ser `hello`; después admite `text_input`,
`tool_call`, `confirm`, gestos y estados de interacción. El simulador de
desarrollo vive en `backend/pipa_core/simulator.py` y no persiste claves.
