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

Al recargar, primero solicita un apagado gracioso. Si el proceso antiguo no
responde, solo tras volver a verificar la línea exacta de `main.py` puede usar
un cierre forzado sobre ese proceso Pipa; nunca usa el PID del puerto ni una
coincidencia por nombre para detener procesos.

Para recargar el código después de una actualización, el instalador lo hace
automáticamente. También puede solicitarse de forma explícita:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\start_agent_hidden.ps1 -Restart
```

La recarga solo considera procesos `python.exe/pythonw.exe` cuya línea incluye
exactamente `-B` y el `windows-agent\main.py` del repositorio; espera a que
terminen antes de iniciar el nuevo proceso. Si Windows no permite verificar la
línea de comandos, no detiene ningún listener ajeno. No existe un endpoint
remoto de reinicio.

Para probar estas funciones sin el Waveshare existe una CLI que solo permite
conectar con el agente local:

```powershell
python .\windows-agent\pipa_cli.py status
python .\windows-agent\pipa_cli.py doctor
python .\windows-agent\pipa_cli.py self-test
python .\windows-agent\pipa_cli.py local-self-test
python .\windows-agent\pipa_cli.py local-capabilities
python .\windows-agent\pipa_cli.py secure-test
python .\windows-agent\pipa_cli.py secure-audio-test
python .\windows-agent\pipa_cli.py integration-test
python .\windows-agent\pipa_cli.py mobile-test
python .\windows-agent\pipa_cli.py mobile-config
python .\windows-agent\secure_identity_admin.py show
python .\windows-agent\pipa_cli.py capabilities
python .\windows-agent\pipa_cli.py integration-status
python .\windows-agent\pipa_cli.py commands
python .\windows-agent\pipa_cli.py protocol
python .\windows-agent\pipa_cli.py intent "busca en Apple Music Daft Punk"
python .\windows-agent\pipa_cli.py preview "busca una partida clasificatoria solo"
python .\windows-agent\pipa_cli.py music-search "Daft Punk" --confirm
python .\windows-agent\pipa_cli.py whatsapp-contact mama "Ya estoy en casa" --confirm
python .\windows-agent\pipa_cli.py whatsapp-contact-open mama --confirm
python .\windows-agent\pipa_cli.py whatsapp-phone-open +34600123456 --confirm
python .\windows-agent\pipa_cli.py discord-contact amigo --confirm
python .\windows-agent\pipa_cli.py discord-call-channel 12345678901234567 --confirm
python .\windows-agent\pipa_cli.py league-status
python .\windows-agent\pipa_cli.py league-search-status
python .\windows-agent\pipa_cli.py league-search solo --confirm
python .\windows-agent\pipa_cli.py open-app codex --confirm
python .\windows-agent\pipa_cli.py codex-open --confirm
python .\windows-agent\pipa_cli.py lock --confirm
```

La prueba `windows-agent/tests/test_secure_serial_gateway.py` recorre también
en memoria el transporte cifrado completo para web, Apple Music, WhatsApp,
Discord y League: anuncia `display`/`touch`, exige `confirm`, ejecuta solo
después de aceptarlo y comprueba que el resultado hacia el dispositivo no
contiene URLs, teléfonos ni datos privados. No abre aplicaciones ni necesita
el hardware.
Además, `self-test` ejecuta un loopback serie v2 interno con una acción web
simulada: comprueba handshake, catálogo, confirmación y redacción sin abrir
puertos, tocar DPAPI ni ejecutar ninguna integración real.
`local-self-test` ejecuta las mismas comprobaciones desde el código actual del
repositorio, sin hablar con el agente residente. Esto permite verificar una
actualización antes de reiniciar el proceso y evita confundir un resultado
antiguo con el código instalado.
`local-capabilities` muestra la matriz completa de integraciones y límites del
código actual, también sin hablar con el agente residente. No abre aplicaciones,
no toca League y no incluye alias, teléfonos, IDs, URLs ni tokens; sirve para
comprobar la configuración que usaría la siguiente recarga del agente.
La prueba `windows-agent/tests/test_secure_tcp_gateway.py` repite ese recorrido
sobre un socket loopback real, que es el camino de referencia para el cliente
móvil.
La prueba windows-agent/tests/test_integration_contract.py comprueba que cada
acción externa siga presente en el router, la ruta local y la confirmación del
dispositivo, y que el catálogo no anuncie envío, llamadas, reproducción o
escritura automática donde no existe.

Las acciones que abren aplicaciones, preparan mensajes o cambian el estado del
juego requieren `--confirm` cuando se ejecutan desde la CLI. La CLI no guarda
credenciales ni acepta una dirección de red: su URL opcional solo admite
literales de loopback. Esa autorización explícita es una
protección del modo local; el flujo del Waveshare usa además la confirmación
ligada a su sesión autenticada y al toque físico.
El comando `intent` solo muestra qué herramienta reconocería una frase y no
abre aplicaciones ni contacta con el agente. `preview` añade la política de
seguridad, los argumentos, la descripción del catálogo y el texto de
confirmación que usaría la sesión, pero tampoco ejecuta la acción. También
valida el contrato local: por ejemplo, avisa si el alias de WhatsApp o
Discord no existe en `contacts.local.json`, sin mostrar el destino ni llamar
al adaptador.

Para una búsqueda web explícita:

```powershell
python .\windows-agent\pipa_cli.py web-search "documentación de Pipa" --confirm
python .\windows-agent\pipa_cli.py open-url "https://example.com" --confirm
python .\windows-agent\pipa_cli.py audio-volume
python .\windows-agent\pipa_cli.py audio-volume 40
python .\windows-agent\pipa_cli.py power-status
python .\windows-agent\pipa_cli.py network-status
python .\windows-agent\pipa_cli.py media-action play_pause
python .\windows-agent\pipa_cli.py timer-create 60 descanso
python .\windows-agent\pipa_cli.py timer-list
python .\windows-agent\pipa_cli.py timer-cancel <timer_id>
```

Para instalar o actualizar el inicio de sesión, abre PowerShell normal. Se
registra para tu usuario y con nivel limitado; no necesita elevarse:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\install_agent_task.ps1
```

Si quieres evitar la pregunta de confirmación, cambia la política solo para
esta ventana y ejecuta el script directamente. Así -Confirm:$false se
interpreta como un SwitchParameter y no como texto de un proceso hijo:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\windows-agent\install_agent_task.ps1 -Confirm:$false
```

La instalación intenta una tarea programada limitada; si Windows no permite
registrarla, usa el inicio `HKCU` y finalmente un acceso directo `.lnk` en
`Startup`. En los tres casos el lanzador es PowerShell oculto, sin `.vbs`, CMD
ni privilegios elevados. La tarea programada corre
como el usuario interactivo, reinicia el agente hasta tres veces y funciona
también con batería; el fallback `HKCU` solo arranca el agente al iniciar
sesión y deja que el propio lanzador evite duplicados. Se retira con
`uninstall_agent_task.ps1`. El instalador y `check_agent_status.ps1` comparan
el ejecutable, argumentos, usuario y trigger exactos; una tarea distinta no se
valida por ser simplemente “oculta”.

## API local

| Método | Ruta | Función |
| --- | --- | --- |
| GET | `/status` | Salud del agente |
| GET | `/self-test` | Diagnóstico local sin efectos externos |
| GET | `/capabilities`, `/integrations/status`, `/commands` | Capacidades, estado de integraciones y frases disponibles, sin datos privados |
| GET | `/apps` | Aplicaciones configuradas |
| POST | `/open-app` | Abrir una app allowlisted |
| POST | `/open-url` | Abrir URL HTTP(S) validada |
| POST | `/web/search` | Abrir búsqueda web |
| POST | `/music/open`, `/music/search` | Abrir Apple Music o una búsqueda |
| GET/POST/DELETE | `/league/status`, `/league/search`, `/league/search/status` | Estado y matchmaking allowlisted |
| GET/POST | `/audio/*`, `/media/action` | Volumen y teclas multimedia |
| GET/POST/DELETE | `/timers` | Temporizadores en memoria |
| POST | `/whatsapp/open`, `/whatsapp/compose`, `/whatsapp/contact/compose`, `/whatsapp/contact/open`, `/whatsapp/phone/open` | Abrir WhatsApp o preparar/abrir chat, sin enviar |
| POST | `/discord/open`, `/discord/channel/open`, `/discord/channel/call`, `/discord/contact/open` | Abrir Discord o preparar un canal, sin iniciar llamada |
| POST | `/discord/contact/call` | Abrir el destino de una llamada; el usuario pulsa Llamar |
| GET | `/pipa/protocol` | Estado del Core y gateway USB |
| POST | `/pipa/challenge` | Desafío Ed25519 local |
| WS | `/pipa/ws` | Sesión autenticada de dispositivo |

La API rechaza hosts no locales, cuerpos de más de 16 KiB y campos inesperados; añade
cabeceras `no-store` y no habilita CORS. Toda petición REST que cambie estado
debe incluir `X-Pipa-Local-Request: 1`; las acciones externas además exigen
`X-Pipa-Local-Confirmation: 1`. Esto bloquea formularios web cross-origin y
ejecuciones accidentales, pero no es una frontera frente a malware del mismo
usuario. Los clientes WebSocket de navegador se rechazan mientras no exista
una UI local con orígenes explícitos.

Las respuestas REST de acciones externas están minimizadas: no devuelven la URL,
el teléfono ni el ID de destino que el adaptador haya usado internamente. Los
adaptadores sí pueden abrir el destino en el equipo, pero cualquier envío de
WhatsApp o llamada de Discord sigue requiriendo la intervención visible del usuario.

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

- Apple Music puede abrir la app configurada o su catálogo web; las búsquedas
  no seleccionan ni reproducen automáticamente una pista concreta. Tras la
  selección, las frases de reproducción/pausa controlan el reproductor activo
  mediante una tecla multimedia.
- League usa únicamente rutas locales allowlisted del cliente. Puede crear o
  reutilizar un lobby, consultar el estado de búsqueda e iniciar/cancelar
  matchmaking. Si el cliente no está listo al confirmar `league_search`, el
  agente abre la aplicación allowlisted y espera como máximo 30 segundos; las
  consultas de estado y la cancelación nunca abren procesos automáticamente.
  La aceptación de una partida no está automatizada: el usuario debe aceptarla
  manualmente cuando aparezca.
  Si League devuelve un estado de matchmaking que Pipa todavía no conoce,
  la búsqueda y la cancelación fallan cerradas y no crean lobby ni inician cola.
  El estado público solo expone `searching`, `not_searching` o `unknown`, y el
  lobby incluye la cola allowlisted cuando se puede identificar.
- El móvil también puede consultar por separado el estado de búsqueda de
  League, la batería/red del PC y los temporizadores locales; esas consultas
  no requieren confirmación. Cancelar un temporizador solo afecta a la memoria
  del agente y no se persiste.
- Codex solo se abre si existe una entrada local `codex`.
- WhatsApp puede abrir una entrada local allowlisted llamada `whatsapp` si la
  configuras, o usar WhatsApp Web como fallback; también puede preparar
  `wa.me`, pero el usuario pulsa `Enviar`.
- Discord puede abrir una entrada local allowlisted llamada `discord` si la
  configuras, o usar la aplicación web/ID validado; el usuario inicia la
  llamada manualmente.
- `GET /integrations/status` solo anuncia esos ejecutables como un booleano
  `app_configured`; nunca devuelve sus rutas ni argumentos.
- Las respuestas locales de esas acciones no incluyen el destino completo ni
  otros datos sensibles derivados de él.
- No se escriben mensajes ni comandos dentro del chat de Codex.
- Los temporizadores y la memoria del Core se pierden al reiniciar.
- El agente admite como máximo 128 temporizadores activos y conserva como
  máximo 256 registros de temporizador.

### Frases deterministas disponibles

El adaptador de texto integrado reconoce, entre otras, estas frases:

```text
abre WhatsApp
abre Discord
abre Apple Music
abre Codex
abre la aplicación calculadora
control multimedia next
reproduce la canción seleccionada
reanuda la pista
detén la música
crea un temporizador 60
abre una URL validada https://example.com
busca en Apple Music Daft Punk
busca Daft Punk en Apple Music
busca una canción de Daft Punk en Apple Music
busca música de Daft Punk
pon música de Daft Punk en Apple Music
reproduce Bohemian Rhapsody en Apple Music
busca la canción Héroes en Apple Music
busca Noticias de Pipa en internet
busca partida
busca partida solo
inicia búsqueda ranked
entra en cola ARAM
busca partida ARAM
busca una partida dentro del LoL
busca una partida clasificatoria solo en League
quiero buscar una partida en el LoL
quiero jugar una partida de ARAM
prepara WhatsApp para +34 600 123 456 y dile Hola Mamá
manda un mensaje a +34 600 123 456 por WhatsApp y dile Hola
manda un mensaje a mama por WhatsApp y dile Hola
manda un mensaje a mama por WhatsApp diciendo Hola
escribe en WhatsApp para +34 600 123 456 y dile Hola
escribe a mama por WhatsApp y dile Hola
abre el chat de mama en WhatsApp
abre WhatsApp con mama y escribe Hola
abre Discord canal 12345678901234567
abre el canal 12345678901234567 en Discord
abre Discord servidor 98765432109876543 canal 12345678901234567
abre el chat de amigo en Discord
llama a amigo por Discord
haz una llamada a amigo por Discord
llama a Discord canal 12345678901234567
llama al canal 12345678901234567 en Discord
llama a Discord servidor 98765432109876543 canal 12345678901234567
llama a Discord
cancela la búsqueda
estado de League
```

Las acciones externas siguen pasando por confirmación cuando llegan desde una
sesión autenticada. Las frases de Apple Music abren una búsqueda; no seleccionan
una canción por sí solas. Después de elegir una pista,
`reproduce la canción seleccionada` envía la tecla multimedia de
reproducción/pausa al reproductor activo. No garantiza que Apple Music sea el
reproductor activo. La de Discord `llama a amigo por Discord`
abre el canal del alias y deja el botón `Llamar` para la persona; no inicia una
llamada. La de WhatsApp abre WhatsApp Web; no pulsa `Enviar`.

Las llamadas de Discord también pueden dirigirse a un ID de canal validado;
Pipα abre el destino y deja el botón `Llamar` para la persona.

`GET /self-test` y los comandos `self-test` y `secure-test` son de solo lectura:
validan la configuración local, las rutas de voz y los constructores de URLs sin abrir
aplicaciones, enviar mensajes ni contactar con League Client. `self-test`
incluye además un simulador v1 y el loopback serie cifrado, completamente inertes;
comprueba también que una acción externa se rechaza sin capacidad `touch` y que
cada comando parametrizado mantiene el mismo número de campos que sus marcadores.
`secure-test`
además ejecuta en memoria el handshake y el cifrado v2; no toca la identidad
persistente de DPAPI.
`secure-audio-test` ejecuta el contrato de audio con muestras PCM sintéticas:
comprueba la compuerta de codec, pantalla, consentimiento y transporte seguro,
el orden cifrado de los chunks, el puente de transcript final y el resumen acotado. No abre micrófono,
puertos, navegador ni aplicaciones, y no guarda las muestras.

`mobile-test` prueba además el cliente móvil de referencia, su anuncio de
pantalla/touch, la confirmación y la reducción de resultados para las cinco
rutas externas (web, Apple Music, WhatsApp, Discord y League); usa handlers
inertes, por lo que no abre sockets, aplicaciones, envía mensajes ni usa la
identidad DPAPI.

`mobile-tcp-test` repite ese flujo sobre un socket TCP efímero de
`127.0.0.1`; comprueba framing, handshake, catálogo, las cinco rutas,
confirmación y redacción sin usar claves persistentes ni ejecutar una
herramienta real.

`mobile-config` comprueba la configuración opt-in de la red sin abrir puertos,
exportar ni devolver claves privadas, y sin modificar el Registro o el firewall.
Valida además que la identidad protegida pueda cargarse con el `server_id`
configurado. Si el modo TCP
está activado, lee de forma no destructiva si existe algún dispositivo móvil
emparejado y falla ante una configuración parcial, wildcard, IP pública, puerto
inválido, una IP privada que no esté asignada a este PC, ausencia de la identidad
protegida o ausencia de emparejamiento. No devuelve IDs, interfaces ni claves
del almacén.

Cuando llegue el iPhone, el firewall se puede preparar de forma explícita
desde una consola elevada. Primero usa `-WhatIf`; la regla queda limitada a la
IP local concreta, al perfil de red `Private` y a `LocalSubnet` o a una IP
privada concreta. No se crea automáticamente al arrancar Pipa:

```powershell
.\scripts\configure_mobile_firewall.ps1 `
  -LocalAddress 192.168.1.20 `
  -Port 18765 `
  -RemoteAddress LocalSubnet `
  -WhatIf

.\scripts\configure_mobile_firewall.ps1 `
  -LocalAddress 192.168.1.20 `
  -Port 18765 `
  -RemoteAddress LocalSubnet
```

Para retirarla:

```powershell
.\scripts\configure_mobile_firewall.ps1 -Remove
```

Para preparar v2 antes de conectar el Waveshare, usa la herramienta separada de
identidad. `init` es el único comando que puede crear el fichero DPAPI; `show`
y `firmware-snippet` solo muestran la clave pública y su fingerprint:

```powershell
python .\windows-agent\secure_identity_admin.py init
python .\windows-agent\secure_identity_admin.py show
python .\windows-agent\secure_identity_admin.py firmware-snippet
```

La salida de `firmware-snippet` se copia únicamente a
`firmware/include/pipa_device_config.local.h`, que está ignorado por Git. No
se debe publicar el fichero de identidad de `%LOCALAPPDATA%\Pipa`.

`doctor` combina esas comprobaciones con `/status`, `/capabilities`,
`/commands`, `/pipa/protocol` y `/self-test` en una única operación de
diagnóstico.

`GET /capabilities` y el comando `capabilities` son de solo lectura. Informan si
Apple Music, League o Codex están configurados y si el cliente de League está
listo, pero nunca devuelven rutas locales, tokens, URLs, contactos ni mensajes.
`GET /integrations/status` y `integration-status` devuelven únicamente esa matriz
de integraciones. En WhatsApp y Discord indican si hay alias locales configurados,
pero nunca exponen sus teléfonos, nombres o IDs.
`GET /commands` y el comando `commands` ofrecen el catálogo de frases que puede
mostrar una UI local. Sus ejemplos usan marcadores como `<teléfono>` y no
contienen datos de esta máquina. El catálogo cifrado del dispositivo añade la
misma matriz de capacidades en formato plano, validada por el Core; el iPhone
la usa para mostrar disponibilidad y pasos manuales sin recibir configuración
privada.

## Configuración de aplicaciones

Copia `config/apps.example.json` como `config/apps.json` y personaliza allí
las rutas. `apps.json` está ignorado y no debe entrar en Git. Los comandos se
ejecutan como una lista de argumentos, sin `shell=True`.
El validador también rechaza lanzadores de shell (`cmd`, PowerShell, WScript,
Bash) y switches como `/c` o `-Command`; configura el ejecutable real de la
aplicación. Para aplicaciones MSIX se puede usar `explorer.exe` con un único
argumento `shell:AppsFolder\\...`. El fichero se limita a 128 KiB, 64
aplicaciones y argumentos acotados; un JSON demasiado grande o ambiguo se
rechaza antes de abrir nada.

Las integraciones pueden usar opcionalmente entradas locales con los IDs
`whatsapp` y `discord`. Añádelas solo si tienes esos ejecutables instalados y
mantén el comando como una lista directa; si no existen, Pipα usa el fallback
web. El agente no necesita ni almacena credenciales de ninguna de las dos
aplicaciones.

## Alias locales de contactos

Si quieres usar nombres en vez de teléfonos o IDs de Discord, copia
`config/contacts.example.json` como `config/contacts.local.json` y edítalo
solo en tu ordenador. Ese fichero está ignorado por Git y no se incluye en
`/capabilities`, `/commands`, los logs ni las respuestas del dispositivo.

```powershell
Copy-Item .\windows-agent\config\contacts.example.json `
  .\windows-agent\config\contacts.local.json
```

Cada contacto puede tener un teléfono de WhatsApp, un canal de Discord o
ambos. Las frases `abre WhatsApp para mama`, `prepara WhatsApp para mama y
dile Hola` y `abre el canal de amigo en Discord` resuelven el alias local,
abren el destino y mantienen la última acción humana: pulsar `Enviar` o
iniciar la llamada. La frase `llama a amigo por Discord` expresa explícitamente
esa intención, pero solo abre el canal y deja el botón para la persona. No existe
una operación automática de envío o llamada. Un alias desconocido se rechaza
antes de pedir confirmación y se vuelve a comprobar al aceptar, por si el
fichero local cambió mientras la confirmación estaba visible. El fichero se
limita a 128 KiB, 64 contactos y aliases acotados.

Para abrir un chat por un número sin guardarlo como alias usa
`whatsapp-phone-open +34600123456 --confirm` o la frase `abre WhatsApp para
+34 600 123 456`. Solo abre el chat y no prepara ni envía ningún mensaje.

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
- cierre tras cinco mensajes de protocolo inválidos consecutivos;
- rate limit de desafíos;
- cierre si el handshake no termina en 20 segundos;
- 12 000 bytes por mensaje;
- cierre al alcanzar diez minutos sin actividad;
- limpieza de la sesión al desconectar.

El endpoint de estado distingue `serial_gateway_configured` y
`serial_gateway_running`; `serial_gateway_connected` confirma además que el
puerto COM está realmente abierto. Un worker que solo está reintentando el
puerto no se considera una conexión de hardware válida.

Para una comprobación física acotada, sin enviar comandos ni mostrar secretos:

```powershell
python .\windows-agent\pipa_hardware_check.py --port COM7
```

La utilidad solo resume marcadores conocidos del arranque (revisión de placa,
expansor, pantalla, touch, ADC y, cuando el firmware los emite, la sonda
ES8311/ES7210). Los codecs de audio son informativos y no hacen fallar la
prueba, porque la captura y reproducción siguen desactivadas. La clave pública
se valida como una clave Ed25519 base64url de 32 bytes, pero nunca se imprime.
Si necesitas comparar la identidad sin copiar la clave, añade `--fingerprint`:

```powershell
python .\windows-agent\pipa_hardware_check.py --port COM7 --fingerprint
```

Solo muestra la huella SHA-256. `pipa_preflight.ps1
-RequireHardware` la ejecuta automáticamente si `PIPA_SERIAL_PORT` está
configurado.
El preflight prefiere `windows-agent/.venv/Scripts/python.exe` para que la
sonda tenga `pyserial` y las dependencias del agente; si no existe, usa el
Python disponible en `PATH`.

Para preparar el primer puerto de forma repetible, desde la raíz del repositorio:

```powershell
.\scripts\prepare_waveshare.ps1 -Port COM7 -WhatIf
.\scripts\prepare_waveshare.ps1 -Port COM7 -RestartAgent
```

La primera orden valida sin escribir configuración. La segunda solo guarda el
COM del usuario después de una sonda correcta y puede reiniciar el agente sin
mostrar una ventana. Ninguna de las dos órdenes empareja claves ni activa v2.

El transporte serie v2 cifrado se activa únicamente con
`PIPA_SERIAL_SECURITY=v2`. Requiere una identidad del agente protegida por
DPAPI, dispositivos emparejados y que el firmware tenga provisionada la clave
pública del agente. Si el handshake falla, se cierra la conexión; nunca se
degrada silenciosamente a v1. Sin hardware, puede seguir validándose con la
prueba Python de secure session, pero no debe activarse en producción todavía.

## Móvil por TCP v2

El transporte móvil está desactivado si no se configura explícitamente
`PIPA_MOBILE_TRANSPORT=tcp-v2`. Para una prueba controlada en la red privada,
usa la IP concreta del PC, nunca una wildcard:

```powershell
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_TRANSPORT', 'tcp-v2', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_BIND', '192.168.1.20', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_PORT', '18765', 'User')
```

Como alternativa, el repositorio incluye un configurador validado y reversible:

```powershell
.\scripts\configure_mobile_transport.ps1 `
  -LocalAddress 192.168.1.20 `
  -Port 18765 `
  -WhatIf

.\scripts\configure_mobile_transport.ps1 `
  -LocalAddress 192.168.1.20 `
  -Port 18765
```

El primer comando solo muestra la operación. El segundo escribe únicamente
variables de entorno del usuario; no crea firewall, no empareja dispositivos y
no abre el listener hasta reiniciar el agente. Para desactivarlo:

```powershell
.\scripts\configure_mobile_transport.ps1 -Disable
```

La configuración manual equivalente es:

```powershell
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_TRANSPORT', 'tcp-v2', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_BIND', '192.168.1.20', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_PORT', '18765', 'User')
```

El listener solo arranca si existe la identidad DPAPI del agente y hay al
menos un dispositivo en `HKLM\SOFTWARE\Pipa\Mobile\Devices`. Rechaza
`0.0.0.0`, `::`, direcciones públicas, frames de más de 96 KiB, más de cuatro
conexiones simultáneas, handshakes lentos y cualquier intento de downgrade a
v1. El payload viaja cifrado con la sesión v2; la app debe fijar fuera de
banda el `server_id`, la clave pública y su fingerprint.

El cliente Python de referencia está en
`secure_mobile_tcp_client.py`. Todavía no es una app iPhone: la implementación
de iOS debe usar CryptoKit, Keychain y una revisión de distribución/actualización
antes de habilitar acceso remoto de uso diario. El gateway refresca el almacén
móvil periódicamente y cierra sesiones revocadas; reiniciar el agente sigue
siendo recomendable tras cambios de provisioning.

## Dispositivos emparejados

Antes de escribir en el Registro, calcula el fingerprint de solo lectura y
compáralo con el mostrado por el firmware a través de un canal físico:

```powershell
.\.venv\Scripts\python.exe .\trusted_unlock_admin.py fingerprint `
  --public-key <CLAVE_PUBLICA_BASE64URL>
```

Solo después de verificarlo usa `pair`. `fingerprint` no necesita elevación y
no modifica el equipo. `pair` exige volver a proporcionar la huella esperada y
rechaza la operación antes de escribir el Registro si no coincide.

La CLI guarda solo claves públicas en HKLM x64 y requiere elevación para
modificarlas:

```powershell
.\.venv\Scripts\python.exe .\trusted_unlock_admin.py list
.\.venv\Scripts\python.exe .\trusted_unlock_admin.py pair `
  --device-id waveshare-01 --public-key <CLAVE_PUBLICA_BASE64URL> `
  --expected-fingerprint <FINGERPRINT_COMPARADO>
.\.venv\Scripts\python.exe .\trusted_unlock_admin.py revoke `
  --device-id waveshare-01 --yes
```

Para un futuro teléfono utiliza los comandos separados `pair-mobile`,
`list-mobile` y `revoke-mobile`; sus claves viven en
`HKLM\SOFTWARE\Pipa\Mobile\Devices` y no conceden acceso al broker de
Trusted Unlock. Consulta [MOBILE_PROTOCOL.md](../MOBILE_PROTOCOL.md) antes de
emparejar una aplicación real.

El gateway móvil refresca las claves periódicamente. El broker de Trusted
Unlock y el gateway USB cargan sus snapshots al arrancar, así que reinícialos
después de emparejar o revocar dispositivos de esos perfiles.

## Trusted Unlock

`trusted_unlock_broker.py` usa un Named Pipe con ACL para el usuario de la
sesión y `SYSTEM`, rechaza clientes remotos y exige la primera instancia del
pipe para evitar que otro proceso suplante el endpoint. Usa desafíos firmados
y tickets de un solo uso. Siempre anuncia
`unlock_enabled=false`; no contiene ningún comando que desbloquee ni produce
una serialización para LogonUI.

## Pruebas

Desde la raíz:

```powershell
python -B -m unittest discover -s windows-agent/tests -p "test_*.py"
python -m compileall -q windows-agent
```
