# Pipα Windows Agent

Agente local para automatización de Windows y puente autenticado con el futuro
Waveshare. Escucha exclusivamente en `127.0.0.1:8765`; no debe publicarse en
la LAN ni reutilizarse como servicio de desbloqueo.

## Instalar y ejecutar

```powershell
python -m venv .\.venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe .\main.py
```

El archivo `requirements.txt` fija las dependencias directas verificadas. Para
inicio silencioso desde la raíz del repositorio:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\start_agent_hidden.ps1

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\check_agent_status.ps1
```

`start_agent_hidden.ps1` prioriza `.venv\Scripts\pythonw.exe`, evita iniciar
un segundo Pipα si ya responde y no muestra CMD. El log rotativo está en
`%LOCALAPPDATA%\Pipa\logs\agent.log`.

Para instalar o actualizar la tarea de inicio de sesión, abre PowerShell como
administrador:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\install_agent_task.ps1
```

La tarea corre como el usuario interactivo con nivel limitado, reinicia el
agente hasta tres veces y funciona también con batería. Se retira con
`uninstall_agent_task.ps1`.

## API local

| Método | Ruta | Función |
| --- | --- | --- |
| GET | `/status` | Salud del agente |
| GET | `/apps` | Aplicaciones configuradas |
| POST | `/open-app` | Abrir una app allowlisted |
| POST | `/open-url` | Abrir URL HTTP(S) validada |
| POST | `/web/search` | Abrir búsqueda web |
| POST | `/music/search` | Abrir búsqueda de Apple Music |
| GET/POST/DELETE | `/league/status`, `/league/search` | Estado y matchmaking allowlisted |
| GET/POST | `/audio/*`, `/media/action` | Volumen y teclas multimedia |
| GET/POST/DELETE | `/timers` | Temporizadores en memoria |
| POST | `/whatsapp/compose` | Preparar chat, sin enviar |
| POST | `/discord/channel/open` | Abrir canal, sin iniciar llamada |
| GET | `/pipa/protocol` | Estado del Core y gateway USB |
| POST | `/pipa/challenge` | Desafío Ed25519 local |
| WS | `/pipa/ws` | Sesión autenticada de dispositivo |

La API rechaza hosts no locales, cuerpos grandes y campos inesperados; añade
cabeceras `no-store` y no habilita CORS. Toda petición REST que cambie estado
debe incluir `X-Pipa-Local-Request: 1`, lo que bloquea formularios web
cross-origin. Los clientes WebSocket de navegador se rechazan mientras no
exista una UI local con orígenes explícitos.

Ejemplo de llamada local:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/media/action' `
  -Headers @{ 'X-Pipa-Local-Request' = '1' } `
  -ContentType 'application/json' -Body '{"action":"play_pause"}'
```

Aun así, los endpoints REST directos son una API para procesos del mismo
usuario, no una frontera frente a software local malicioso. El canal de
dispositivo sí exige firma Ed25519 y confirmación para herramientas externas.

## Capacidades y límites

- Las búsquedas abren resultados; Apple Music no garantiza reproducción
  automática de una pista concreta.
- League usa únicamente rutas locales allowlisted del cliente. Puede crear el
  lobby e iniciar/cancelar búsqueda, pero Riot puede cambiar esa API interna.
- Codex solo se abre si existe una entrada local `codex`.
- WhatsApp prepara `wa.me`; el usuario pulsa `Enviar`.
- Discord abre un ID validado; el usuario inicia la llamada.
- No se escriben mensajes ni comandos dentro del chat de Codex.
- Los temporizadores y la memoria del Core se pierden al reiniciar.

## Configuración de aplicaciones

Copia `config/apps.example.json` como `config/apps.json` y personaliza allí
las rutas. `apps.json` está ignorado y no debe entrar en Git. Los comandos se
ejecutan como una lista de argumentos, sin `shell=True`.

## Waveshare por USB

El gateway solo se activa con un puerto explícito:

```powershell
[Environment]::SetEnvironmentVariable('PIPA_SERIAL_PORT', 'COM7', 'User')
```

Reinicia la sesión o el agente después. El puerto debe ser `COM1`–`COM999` y
el baudrate permitido está acotado. El transporte usa JSON UTF‑8 por líneas;
las líneas de diagnóstico del firmware empiezan por `#` y se ignoran.

Cada conexión aplica:

- desafío Ed25519 de un solo uso;
- máximo de tres fallos de autenticación;
- rate limit de desafíos;
- 12 000 bytes por mensaje;
- cierre tras diez minutos sin actividad;
- limpieza de la sesión al desconectar.

El endpoint de estado distingue `serial_gateway_configured` y
`serial_gateway_running` para no confundir una configuración inválida con un
gateway operativo.

## Dispositivos emparejados

La CLI guarda solo claves públicas en HKLM x64 y requiere elevación para
modificarlas:

```powershell
.\.venv\Scripts\python.exe .\trusted_unlock_admin.py list
.\.venv\Scripts\python.exe .\trusted_unlock_admin.py pair `
  --device-id waveshare-01 --public-key <CLAVE_PUBLICA_BASE64URL>
.\.venv\Scripts\python.exe .\trusted_unlock_admin.py revoke `
  --device-id waveshare-01 --yes
```

Reinicia el agente y el broker después de emparejar o revocar, porque sus
verificadores cargan las claves públicas al arrancar.

## Trusted Unlock

`trusted_unlock_broker.py` usa un Named Pipe con ACL para el usuario de la
sesión y `SYSTEM`, desafíos firmados y tickets de un solo uso. Siempre anuncia
`unlock_enabled=false`; no contiene ningún comando que desbloquee ni produce
una serialización para LogonUI.

## Pruebas

Desde la raíz:

```powershell
python -B -m unittest discover -s windows-agent/tests -p "test_*.py"
python -m compileall -q windows-agent
```
