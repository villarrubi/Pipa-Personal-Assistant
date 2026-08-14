# Pipα Core

Núcleo independiente del transporte para sesiones de dispositivo, protocolo,
estado de UI, memoria temporal, herramientas y confirmaciones. Hoy se aloja
dentro del Windows Agent y se usa tanto desde USB serie como desde el
WebSocket local `/pipa/ws`.

## Autenticación

1. El dispositivo emparejado envía `challenge_request` con su `device_id`.
2. El Core devuelve un desafío corto con nonce, operación, audiencia y
   caducidad.
3. El dispositivo firma el JSON canónico completo con su clave Ed25519.
4. Envía `hello` con `challenge_id`, firma y metadatos opcionales.
5. El Core consume el desafío y crea una sesión temporal.

Para compatibilidad local también existe `POST /pipa/challenge`; el flujo
preferido mantiene desafío y sesión en el mismo transporte.

La política de conexión está centralizada en `pipa_core/connection.py`: USB y
WebSocket comparten rate limit, máximo de fallos, timeout de autenticación de
20 segundos, timeout de sesión autenticada y cleanup. Las
claves privadas no existen en este módulo ni se persisten en Windows.
El protocolo v1 autentica e integra los mensajes, pero no cifra sus payloads;
la futura voz o conexión móvil necesita un canal de sesión cifrado antes de
transportar audio o datos privados.
El registro limita a 32 sesiones autenticadas simultáneas y a 2 por dispositivo.
Además, el propio registro elimina una sesión sin tráfico durante 15 minutos
como segunda barrera, aunque un transporte futuro olvide ejecutar su cleanup;
al hacerlo también se invalidan sus confirmaciones pendientes.

## Mensajes de protocolo v1

Antes de autenticar:

- `challenge_request`
- `hello`

Después de autenticar:

- `ping`, `device_status`
- `device_hello` (anuncio cifrado de metadatos/capacidades en sesiones v2)
- `catalog_request` (solicitud cifrada del catálogo UI no sensible)
- `wake`, `hold_start`, `hold_end`, `audio_end`, `abort`
- `gesture`, `text_input`
- `tool_call`, `confirm`

El parser rechaza versiones desconocidas, campos inesperados, textos, listas y
argumentos de herramientas sobredimensionados, telemetría inválida, tipos
ambiguos y objetos JSON con claves repetidas (también si una clave está
escapada). Cambios incompatibles requieren aumentar `protocol_version`.

Los `tool_call` estructurados del cliente móvil pueden incluir
`request_digest`, un SHA-256 del JSON canónico compacto con `name` y
`arguments`. El Core lo recalcula y rechaza la solicitud antes del router si
no coincide. Cuando se crea una confirmación, solo devuelve ese digest —nunca
los argumentos— para que la UI móvil pueda comprobar que la acción que se
aprueba es exactamente la que se previsualizó. El campo es opcional para
mantener compatibilidad con el protocolo del Waveshare actual.

`device_status.audio_state` es opcional para clientes antiguos y, cuando está
presente, solo admite los estados cerrados `disabled`, `probe_only`,
`codec_ready`, `listening`, `draining` y `error`. El Core lo conserva en la
sesión como diagnóstico; no habilita voz ni sustituye el consentimiento, la
pantalla o el transporte cifrado.

Antes de crear una confirmación o llamar a un adaptador, `ToolRouter` aplica el
contrato de argumentos registrado para la herramienta: campos obligatorios,
tipos, límites, opciones allowlisted y validaciones puras de URL, teléfono o
cola. Así un `tool_call` estructurado del móvil o del Waveshare falla cerrado
sin dejar una confirmación pendiente; los argumentos ordinarios se vuelven a
validar al consumirla. Los adaptadores que resuelven destinos privados por
alias (WhatsApp y Discord) guardan además una instantánea interna del destino
validado al crear la confirmación. Esa instantánea no se incluye en el sobre
de confirmación y evita que un cambio concurrente del fichero local redirija
la acción después de que el usuario la haya aprobado.

Una sesión v2 se crea sin capacidades físicas. Hasta aceptar un único
`device_hello`, el Core solo atiende `ping`, `device_status` y `abort`; el
catálogo, la UI, las órdenes y las confirmaciones devuelven
`device_hello_required` sin crear pendientes ni ejecutar handlers. El catálogo
también se compara con la definición registrada de cada herramienta y se
rechaza completo si su política `safe`/`unsafe` o `requires_confirmation` no
coincide.

## Herramientas y confirmaciones

Las herramientas `unsafe` no se ejecutan al primer mensaje. El Core devuelve
`confirm_request`; su identificador pertenece a la sesión que lo creó, caduca
en 30 segundos y solo puede consumirse una vez. Abortar o cerrar la sesión
invalida las confirmaciones pendientes; mientras una confirmación está visible
no se acepta otra orden. El resultado enviado al dispositivo usa una etiqueta
fija, un estado booleano y un caption acotado generado por una allowlist; los
datos devueltos por los handlers no cruzan el transporte físico. Así no se
devuelven URLs, mensajes, nombres de interfaces, IDs de temporizadores,
telemetría detallada ni memoria privada a la pantalla. La memoria de
pendientes está limitada globalmente y por sesión.

`catalog_request` solo devuelve descriptores acotados de comandos (`id`, frase,
descripción y política de confirmación), metadata tipada de parámetros y, para
acciones directas, argumentos fijos allowlisted. En el agente Windows también
incluye una matriz plana de capacidades de integración. El Core filtra campos
desconocidos, longitudes, duplicados y cantidades antes de enviarlos; la matriz solo admite
booleanos, textos cortos y listas de textos cortas. No incluye URLs,
configuración local, contactos, tokens ni resultados de herramientas.

Los límites temporales son cerrados: una confirmación, desafío, ticket o sesión
deja de ser válido exactamente en su `expires_at`/timeout, no después.

El adaptador de frases en español es deliberadamente determinista. Una futura
capa STT/LLM debe producir `text_input` o `tool_call`; no debe mezclarse con
los handlers que controlan Windows. Para el camino de audio seguro existe
además `PipaCore.handle_transcript`: recibe un transcript final, lo vuelve a
validar y lo entrega al mismo parser, confirmador y reductor de resultados que
usa `text_input`. Así el proveedor STT no puede crear una ruta de ejecución
alternativa.

Mientras no exista STT ni transporte de audio seguro, `hold_end` y `audio_end`
terminan de forma explícita con `voice_unavailable` y devuelven la sesión a
`idle`; nunca dejan la pantalla bloqueada en `thinking`.

`remember_fact` y `recall_memory` usan memoria de proceso, acotada a 100 hechos
por dispositivo y 256 dispositivos. No se persisten datos personales hasta
diseñar cifrado, borrado y exportación.

Las herramientas `unsafe` también requieren que la sesión anuncie `display` y
`touch`; si el hardware no inicializó la superficie física de confirmación, la
acción se rechaza sin crear un pendiente. En v2 la sesión nace sin esas
capacidades y solo se habilita después de aceptar una única `device_hello`
autenticada y cifrada; así un cliente que omita el anuncio no puede confirmar
acciones externas.

## Simulador

```powershell
python backend/pipa_simulator.py
```

Genera una identidad efímera en RAM, completa la autenticación y prueba una
herramienta inocua y otra que exige confirmación `display` + `touch`. No
modifica Windows ni escribe claves.

## Pruebas

```powershell
python -B -m unittest discover -s backend/tests -p "test_*.py"
```
