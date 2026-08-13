# Seguridad de Pipα

## Garantía actual

Pipα está en desarrollo y **no es todavía un producto de autenticación**. El
Credential Provider muestra una tile adicional, pero `GetSerialization` no
entrega credenciales y el broker anuncia siempre `unlock_enabled=false`.
Contraseña, PIN, Windows Hello y los providers normales siguen siendo la vía
de recuperación y acceso.

## Fronteras de confianza

- **API REST local:** automatización para procesos del mismo usuario. Loopback,
  validación de Host, sin CORS, cuerpos acotados y cabeceras obligatorias para
  mutaciones y acciones externas. No es un sustituto de la confirmación del
  dispositivo y no protege frente a malware que ya se ejecute con la misma
  cuenta.
- Las respuestas REST de acciones externas se minimizan y omiten URLs, teléfonos
  e identificadores de destino; esos valores solo viven en el adaptador local
  durante la apertura validada.
- Las respuestas de validación HTTP tampoco repiten los valores de entrada, para
  que una solicitud malformada no convierta un teléfono, mensaje o URL en una
  respuesta de diagnóstico.
- **USB/WebSocket de dispositivo:** exige una clave Ed25519 emparejada, desafío
  de un solo uso, sesión temporal y confirmaciones ligadas a sesión. El
  protocolo v1 aporta autenticación e integridad, pero no confidencialidad del
  payload: no se deben transportar secretos por él.
- **Sesión segura v2 preparada:** `SECURE_SESSION_PROTOCOL.md` y
  `windows-agent/secure_session.py` definen X25519 efímero autenticado,
  HKDF-SHA256 y ChaCha20-Poly1305 con contador anti-replay. Está aislada y no
  se activa por defecto; el record layer, el cliente de handshake C++, el
  gateway serie opt-in y el vector determinista ya compilan, pero falta
  ejecutar el vector en el firmware físico, provisionar la identidad Ed25519
  del agente y completar la migración controlada desde v1.
- El gateway serie v2 solo se activa con `PIPA_SERIAL_SECURITY=v2`; una vez
  iniciado el handshake no acepta una línea v1 como fallback. La identidad
  privada del agente se protege con DPAPI y la clave pública del agente debe
  provisionarse en el firmware por un canal físico.
- **TCP móvil v2:** `PIPA_MOBILE_TRANSPORT=tcp-v2` es opt-in y exige una IP
  privada o loopback concreta, un puerto explícito, identidad DPAPI del agente
  y claves del almacén móvil separado. El canal cifra el payload con la sesión
  v2, rechaza wildcard/public binding, limita a cuatro conexiones, aplica
  timeout y nunca degrada a v1. El listener no se crea si falta provisioning o
  configuración completa.
  `pipa_cli.py mobile-config` permite validar estos requisitos sin abrir el
  listener ni modificar el Registro o reglas del firewall; el almacén móvil
  solo se consulta de forma no destructiva y la salida reduce el resultado a
  indicadores booleanos. La identidad DPAPI se valida contra el `server_id`,
  pero nunca se exporta ni se incluye en la salida.
 - **Named Pipe experimental:** ACL para usuario y `SYSTEM`, rechazo de clientes
  remotos y primera instancia exclusiva del pipe, más firma del dispositivo.
  No desbloquea.
 - **Credential Provider:** código cargado por LogonUI; se mantiene separado,
  rechaza serializaciones externas y sin serialización de salida hasta completar
  revisión y recuperación.
- **Firmware:** la clave vive en NVS. Sin Secure Boot y cifrado de Flash no se
  considera resistente a extracción física.

## Controles implementados

- Ed25519 con JSON canónico; nonce aleatorio de 32 bytes.
- Desafíos de 30 segundos, consumibles una vez y acotados en memoria; el
  instante exacto de caducidad ya se considera inválido.
- Revocación de claves públicas y rechazo de reemplazo silencioso.
- Máximo de tres fallos por conexión y rate limit de desafíos.
- Mensajes USB/WebSocket de máximo 12 000 bytes, frames TCP móvil acotados a
  96 KiB, argumentos de herramienta de máximo 4 KiB y esquema estricto.
- Respuestas de protocolo sin eco de errores controlados por la entrada,
  límite de salida del gateway y cierre tras cinco mensajes inválidos seguidos.
- Peticiones HTTP locales limitadas a 16 KiB incluso si no declaran
  `Content-Length`.
- Timeout de autenticación, inactividad y heartbeat; el límite exacto de
  inactividad cierra la sesión y el cleanup ocurre al desconectar.
- Las excepciones inesperadas de la API se registran solo en el log local con
  un nombre de tipo acotado y la respuesta HTTP siempre es genérica; no se
  devuelven rutas, mensajes, tokens ni detalles del adaptador.
- Confirmaciones de 30 segundos, de un solo uso y ligadas a sesión.
- Confirmaciones acotadas globalmente y por sesión para evitar acumulación o
  agotamiento de memoria.
- Los registros anti-replay de Trusted Unlock tienen un límite absoluto además
  de su caducidad; una entrada expulsada sigue siendo rechazada como desconocida.
- Sesiones autenticadas limitadas globalmente y por dispositivo para evitar
  conexiones duplicadas indefinidas.
- Abortar, desconectar o caducar una sesión invalida sus confirmaciones
  pendientes; no se aceptan órdenes concurrentes mientras se muestra una.
- El Core no crea confirmaciones para acciones externas si el dispositivo no
  anuncia simultáneamente pantalla y touch funcionales.
- La CLI local exige `--confirm` para acciones externas o cambios de estado;
  `preview` solo inspecciona y no ejecuta. Su URL opcional acepta únicamente
  literales de loopback, nunca nombres resolubles como `localhost`.
- Herramientas allowlisted y `subprocess` sin shell; la configuración de apps
  rechaza lanzadores `cmd`/PowerShell/WScript/Bash y switches de intérprete,
  por lo que las aplicaciones deben arrancar mediante su ejecutable directo.
- Los alias de contactos viven únicamente en `windows-agent/config/contacts.local.json`;
  se validan con destinos acotados, no se publican en capacidades ni catálogo y
  solo preparan WhatsApp o abren Discord. Un alias inexistente se rechaza antes
  de crear una confirmación y se vuelve a validar al consumirla. Envío y llamada
  siguen requiriendo una acción humana visible.
- Las configuraciones locales de aplicaciones y contactos se leen con un límite
  de 128 KiB y un número máximo de entradas; JSON sobredimensionado, ambiguo o
  con lanzadores de shell se rechaza antes de ejecutar una aplicación.
- URLs limitadas a HTTP(S), sin credenciales embebidas.
- Protección contra formularios cross-origin y rechazo de WebSocket de navegador.
- Cabecera adicional de confirmación local para endpoints que abren apps,
  URLs, mensajes, canales, matchmaking o bloquean Windows.
- Gateway serie opt-in y sin listener de red.
- El preflight comprueba en runtime que el puerto del agente solo escucha en
  loopback; un binding en `0.0.0.0` o una interfaz externa hace fallar la
  verificación.
- El cargador Waveshare exige `-AllowDevelopmentFirmware` porque las imágenes
  actuales aún no tienen Secure Boot ni cifrado de Flash; no se puede aceptar
  una imagen de desarrollo por omisión como si fuera una release.
- Antes de cargar esa imagen, el flasheador consulta en modo solo lectura
  `SPI_BOOT_CRYPT_CNT`, `SECURE_BOOT_EN` y `SECURE_VERSION`; si el chip ya tiene
  cifrado, Secure Boot o anti-rollback activo, aborta para no intentar cargar
  plaintext sobre una configuración protegida.
- Temporizadores activos y registros completados acotados para evitar
  acumulación indefinida.
- Memoria temporal limitada por hecho, dispositivo y número total de
  dispositivos.
- Tarea de inicio del agente por usuario, oculta y con nivel limitado; no
  requiere ni solicita privilegios administrativos. El instalador y el
  diagnóstico aceptan la tarea o fallback solo si apuntan exactamente al
  lanzador de Pipa, con sus argumentos, usuario interactivo y trigger de
  inicio; una tarea arbitraria de PowerShell no se considera válida.
- Logs locales rotativos que no registran cuerpos, firmas, claves ni tokens.
- La actualización del agente usa una ruta de apagado solo en loopback y con
  cabecera específica para que el propio servidor cierre limpiamente; el
  fallback de proceso exige la línea de comandos exacta y nunca termina un PID
  arbitrario por el mero hecho de escuchar en el puerto del agente.
- La identidad del agente v2 se protege con DPAPI del usuario actual en
  `secure_identity_store.py`; el fichero local contiene solo el blob cifrado y
  está excluido de Git. El agente v1 no lo toca; el gateway v2 solo carga una
  identidad ya provisionada y nunca la crea durante el arranque.
- Las respuestas de herramientas se reducen a un sobre de estado y un caption
  corto generado por allowlist antes de cruzar USB/WebSocket; el resultado
  interno no se envía al dispositivo. Los captions no incluyen URLs, mensajes,
  contactos, nombres de interfaces, IDs ni etiquetas de temporizadores.
- Los `confirm_request` del dispositivo también usan etiquetas fijas por
  herramienta; nunca interpolan teléfonos, mensajes, URLs, contactos, IDs o
  argumentos de League en el resumen visible.
- El `ToolRouter` valida el contrato de argumentos de cada herramienta antes de
  crear una confirmación: rechaza campos extra, tipos, longitudes, opciones y
  formatos inválidos sin dejar un pendiente; vuelve a validarlo al consumir la
  confirmación.
- El catálogo móvil solo puede añadir la matriz allowlisted de capacidades
  públicas (`available`, límites manuales y colas). El Core rechaza grupos,
  campos desconocidos, valores anidados o tipos inesperados; un catálogo
  inválido se descarta completo.
- El canal JSON v2 cifra el objeto completo, autentica una AAD fija y exige un
  sobre estricto antes de entregar el contenido al parser del Core; permanece
  opt-in y aislado del WebSocket v1.
- El cliente móvil de referencia prueba en memoria el handshake, el anuncio de
  `display`/`touch`, la confirmación y la reducción de resultados para web,
  Apple Music, WhatsApp, Discord y League. El cliente TCP de referencia prueba
  además el framing real en loopback; ambos usan handlers inertes, no
  persisten claves ni ejecutan acciones reales durante el diagnóstico.
- El firmware y el cliente iOS rechazan UTF-8 malformado, controles C0/C1 y
  formato bidireccional o invisible antes de mostrar una confirmación.
- Las validaciones compartidas de Windows y iOS rechazan además puntos de
  código Unicode de uso privado en búsquedas, mensajes y metadatos mostrados.
- Las claves móviles, cuando se emparejen, usan
  `HKLM\SOFTWARE\Pipa\Mobile\Devices`, separado del almacén experimental de
  Trusted Unlock; emparejar un teléfono no lo añade automáticamente al broker.
  El gateway TCP refresca el almacén periódicamente, invalida una sesión si la
  clave fue revocada o reemplazada y cierra sesiones si el almacén deja de ser
  legible.
- El adaptador v2 del Core limpia la sesión y las confirmaciones si falla un
  frame autenticado, limita errores de protocolo y no crea un listener nuevo.
- El diagnóstico `self-test` recorre además el gateway serie v2 completo sobre
  un endpoint en memoria: verifica framing, handshake, catálogo, confirmación
  y redacción sin abrir un puerto, tocar DPAPI ni ejecutar integraciones reales.
- El mismo diagnóstico recorre el lifecycle v1 con un dispositivo efímero:
  autentica, procesa texto, exige confirmación para una acción externa y rechaza
  esa acción si no se anuncia `touch`; todos los handlers son inertes.
- El diagnóstico `secure-audio-test`, incluido también en `self-test`, recorre
  el framing PCM cifrado con muestras sintéticas, exige la compuerta de codec,
  pantalla, consentimiento y transporte seguro, y solo expone contadores
  booleanos/acotados; no abre micrófono, red, serie ni guarda muestras.
- El diagnóstico `integration-test`, incluido también en `self-test`, comprueba
  los destinos HTTPS allowlisted, las colas de League y que Apple Music,
  WhatsApp, Discord, League y Codex mantengan sus pasos manuales; usa valores
  sintéticos y no abre aplicaciones, envía mensajes, llama ni contacta con
  League.
- El núcleo iOS `mobile-ios/PipaMobileCore` no expone la clave privada de la
  identidad como API pública; la identidad se genera/carga mediante Keychain
  con `ThisDeviceOnly`, y el cliente fija la clave pública y el `server_id` del
  agente antes de aceptar `ServerHello`.
- La configuración no secreta de conexión de iOS (host privado, puerto,
  `server_id`, clave pública y `identity_id`) se guarda en un registro Keychain
  separado, no sincronizable y accesible solo con el dispositivo desbloqueado;
  la UI permite borrarla sin borrar la identidad Ed25519.
- Ese registro se valida al guardar y cargar: se rechazan controles Unicode,
  identificadores fuera de la gramática, puertos inválidos, claves públicas
  malformadas y hosts que no sean literales privados/loopback/link-local. La
  configuración inicial puede permanecer parcial mientras se completa el
  emparejamiento.
- La caché anti-replay de `session_id` v2 tiene límite de 4.096 entradas y
  caducidad de 30 minutos; no puede crecer indefinidamente por conexiones USB.
- CI con tests Python, Ruff, auditoría de dependencias, build de firmware y
  smoke test del Credential Provider.
- Una prueba de contrato cruza el catálogo público, el router real, las rutas
  de confirmación local y las etiquetas fijas del dispositivo para evitar que
  una integración nueva quede expuesta sin sus barreras.
- Comprobaciones separadas del árbol actual y de toda la historia Git.
- La auditoría de higiene prueba además patrones `.gitignore` con rutas
  ficticias de configuraciones, claves, builds, logs, capturas, grabaciones y
  trazas; así una exclusión debilitada falla antes de un commit.

## Límites que no se deben romper

- No guardar contraseñas, PIN, cookies, tokens estáticos o claves privadas en
  Windows, logs o Git.
- No enlazar ningún transporte Pipa a `0.0.0.0` ni exponerlo mediante port
  forwarding; el TCP móvil debe usar solo una IP privada explícita y una red
  bajo control del usuario hasta que exista una revisión de despliegue.
- No añadir `/unlock` HTTP ni aceptar Wake-on-LAN como autenticación.
- No desactivar providers normales ni modificar políticas de recuperación.
- No convertir el broker en servicio privilegiado sin revisar ACL, identidad
  del cliente, lifecycle, actualizaciones y rollback.
- No serializar credenciales en LogonUI sin revisión independiente y pruebas
  de bloqueo/recuperación.
- No emparejar una clave sin comparar su fingerprint físicamente.
- El comando `trusted_unlock_admin.py fingerprint` permite hacer esa
  comparación sin escribir en el Registro; `pair` se ejecuta solo después.
- `pair` exige además `--expected-fingerprint` y compara la huella antes de
  modificar el Registro; una discrepancia no escribe nada.
- No enviar WhatsApp, iniciar llamadas o ejecutar acciones externas sin la
  confirmación prevista.
- Las entradas locales opcionales `whatsapp` y `discord` solo se ejecutan a
  través de la misma allowlist directa que el resto de aplicaciones; si faltan
  o son inválidas, se usa el navegador. Las capacidades solo exponen si están
  configuradas, nunca sus rutas o argumentos.
- Una orden confirmada de búsqueda de League puede abrir el cliente allowlisted
  si no está iniciado, pero solo espera un tiempo acotado y no amplía la
  allowlist ni ejecuta comandos del sistema; estado, cancelación y estados
  desconocidos siguen siendo fail-closed si el cliente no está disponible. La
  aceptación de una partida requiere una acción visible del usuario.

## Datos prohibidos en Git

- `.env`, tokens, claves, certificados privados, perfiles RDP/registro y bases
  de credenciales.
- `DerivedData`, `xcuserdata`, estados de Xcode y artefactos de Swift Package
  Manager generados en equipos de desarrollo.
- `windows-agent/config/apps.json` y configuración real del dispositivo.
- Rutas de perfiles, IP/MAC locales, SSID y contraseña Wi‑Fi.
- DLL, EXE, PDB, objetos, `.pio`, CMake/Visual Studio, venvs, logs y dumps.
- Capturas de LogonUI o mensajes que muestren datos personales.

Antes de publicar:

```powershell
.\scripts\check_repo_hygiene.ps1
.\scripts\check_git_history.ps1
git status --short
```

`.gitignore` solo evita inclusiones nuevas. Si algo sensible entró en un
commit, hay que reescribir la historia, invalidar cualquier secreto real y
actualizar el remoto de forma coordinada.

## Amenazas que deben probarse

1. proceso local no autorizado contra REST, WebSocket y Named Pipe;
2. replay de respuesta, confirmación y ticket ya consumidos;
3. dispositivo desconocido, revocado o con NVS corrupta;
4. mensajes enormes, JSON inválido, campos extra y floods de desafíos;
5. desconexión USB, reinicio del agente, timeout y reloj incorrecto;
6. DLL/Registro ausentes, alterados o de arquitectura equivocada;
7. corte de corriente durante actualización del dispositivo;
8. recuperación con contraseña/PIN/Hello y rollback del provider.

## Riesgos pendientes por hardware

- Validar fuente de entropía y proceso de provisión en la unidad real.
- Habilitar Secure Boot, cifrado de Flash y anti-rollback.
- Diseñar actualización firmada con partición recuperable.
- Verificar que pantalla, touch, micrófono y audio no bloqueen el loop de
  seguridad ni filtren información.
- Decidir si la voz se procesa localmente o se transmite; cualquier opción
  requiere consentimiento, indicador visible, límites y política de borrado.
- El dictado opcional del iPhone exige reconocimiento en dispositivo y solo
  rellena el editor; no envía comandos ni confirma acciones. Debe verificarse
  en un iPhone real que no exista fallback remoto involuntario.
- El protocolo JSON actual no debe transportar audio de micrófono en claro;
  antes de añadir STT hay que diseñar cifrado/autenticación por trama o
  procesamiento local en el dispositivo.
- Los métodos de entrada de texto del firmware v1 y v2 validan UTF-8, rechazan
  controles invisibles y aceptan solo las fuentes de protocolo allowlisted antes
  de serializar el comando. Los gestos producidos por ambos transportes usan la
  misma política allowlist que el parser del Core.
- Para voz o móvil, solo se podrá usar la sesión v2 después de validar los
  vectores Python↔firmware y Python↔móvil, además de una política de rotación,
  revocación y actualización. No basta con reutilizar la firma Ed25519 como si
  fuera cifrado.

## Recuperación

- Tarea del agente: `windows-agent/uninstall_agent_task.ps1`.
- Credential Provider: `trusted-unlock/uninstall.ps1 -WhatIf` y después sin
  `-WhatIf` desde PowerShell administrador.
- Dispositivo: revocar la clave pública y reiniciar agente/broker.
- Si Pipα falla, usar siempre el método normal de Windows.

## Reportar un problema

No publiques rutas, fingerprints completos, logs sin revisar ni detalles de
cuentas en una issue pública. Describe impacto, precondiciones y reproducción
con datos anonimizados.
