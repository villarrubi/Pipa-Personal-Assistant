# Cliente móvil de Pipα (v2)

Este documento define el contrato que debe seguir la aplicación para iPhone.
El repositorio incluye un cliente de referencia en memoria en
`windows-agent/secure_mobile_client.py`, un núcleo Swift nativo y una UI SwiftUI
mínima en `mobile-ios/`. El paquete Swift aún no es una app distribuible, pero
implementa la identidad Keychain, el handshake CryptoKit, el record layer
cifrado, el cliente TCP v2 y la pantalla de confirmaciones.

## Estado actual

- El cliente móvil de referencia completa el handshake v2, anuncia una UI con
  `display` y `touch`, envía comandos y confirma acciones.
- `python .\windows-agent\pipa_cli.py mobile-test` ejecuta el flujo completo
  sin sockets, navegador, aplicaciones, League ni claves persistentes.
- El agente no abre el transporte móvil por defecto y todavía no existe una
  app iPhone distribuible. El paquete Swift ya contiene `PipaMobileCore`,
  `PipaMobileUI` y una plantilla de `App`; el adaptador TCP v2 y un cliente
  Python de referencia permiten probar el flujo real sobre `127.0.0.1`, sin
  tocar claves persistentes ni ejecutar acciones durante el diagnóstico.
- El paquete Swift se debe compilar y probar en Xcode sobre macOS antes de
  distribuirlo o enlazarlo con un proyecto iOS final. Este equipo Windows no
  tiene `swift` ni `xcodebuild`, por lo que el preflight revisa estructura y
  controles, mientras CI macOS compila y ejecuta las pruebas del paquete.

## Identidad y enrolamiento

Cada instalación móvil debe tener una identidad Ed25519 distinta, generada en
el propio teléfono y conservada en el almacén seguro del sistema. La clave
privada no se exporta, no se incluye en un QR y no se envía al agente.

El teléfono debe fijar por un canal fuera de banda:

- `server_id`, por defecto `pipa-agent-v2`;
- la clave pública Ed25519 del agente;
- el fingerprint que el usuario haya comparado localmente.

La UI de referencia no permite conectar hasta que el usuario marque que ha
comparado el fingerprint mostrado con el agente por ese canal externo. Esta
marca no se persiste y se invalida si cambia `server_id` o la clave pública;
guardar una configuración no equivale a volver a verificar la identidad.

El agente solo debe aceptar la clave pública del teléfono después de una
acción explícita de emparejamiento. Revocar un teléfono elimina su clave del
almacén de dispositivos; el gateway TCP v2 refresca ese almacén y cierra las
sesiones activas revocadas. Si el proceso no puede leer el almacén, cierra las
sesiones móviles por seguridad. Cambiar una clave sin una acción de revocación
y nuevo fingerprint no está permitido.

El almacén móvil está separado del almacén experimental de Trusted Unlock. En
Windows, el administrador utilizará:

```powershell
python .\windows-agent\trusted_unlock_admin.py pair-mobile `
  --device-id iphone-main `
  --public-key <CLAVE_PUBLICA_BASE64URL> `
  --expected-fingerprint <FINGERPRINT_COMPARADO>

python .\windows-agent\trusted_unlock_admin.py list-mobile
python .\windows-agent\trusted_unlock_admin.py revoke-mobile --device-id iphone-main --yes
```

Estos comandos solo guardan la clave pública en
`HKLM\SOFTWARE\Pipa\Mobile\Devices`. No habilitan el transporte móvil ni el
desbloqueo de Windows.

## Sesión

1. El teléfono genera un `session_id`, un nonce de 32 bytes y una clave
   X25519 efímera.
2. Envía `ClientHello` firmado con su identidad Ed25519.
3. Verifica `ServerHello` con la clave pública fijada y comprueba el
   `server_id` esperado.
4. Ambos extremos derivan claves direccionales con HKDF-SHA256.
5. Cada mensaje se cifra con ChaCha20-Poly1305, AAD `pipa/json/v2`, contador
   estricto y el `session_id` del sobre.

El contenido cifrado sigue siendo el protocolo Core v1: `device_hello`,
`catalog_request`, `text_input`, `tool_call`, `confirm`, `ping` y
`device_status`. Después del `device_hello`, el teléfono puede pedir el
catálogo no sensible:

```json
{"protocol_version": 1, "type": "catalog_request"}
```

El primer mensaje de Core que debe enviar el teléfono después del handshake es
`device_hello`. Hasta que el agente lo acepte, solo responde a `ping`,
`device_status` y `abort`; cualquier catálogo, texto, gesto, orden o
confirmación recibe `device_hello_required`, sin crear confirmaciones ni
ejecutar herramientas. El anuncio solo se acepta una vez por sesión.

El agente devuelve solo descriptores de UI filtrados; no devuelve la
configuración del PC ni resultados de aplicaciones. El sobre `catalog` puede
incluir además una matriz plana y acotada de capacidades de integración:

```json
{
  "protocol_version": 1,
  "type": "catalog",
  "commands": [],
  "capabilities": {
    "apple_music": {
      "available": true,
      "playback": false,
      "requires_manual_selection": true
    },
    "discord": {
      "available": true,
      "start_call": false,
      "requires_manual_call": true
    },
    "league": {
      "available": true,
      "matchmaking": true,
      "accept_match": false,
      "requires_manual_accept": true
    }
  }
}
```

Solo se permiten claves cortas y valores booleanos, textos cortos o listas de
textos cortas. No se permiten objetos anidados, números, rutas, IDs, URLs,
tokens, teléfonos, contactos ni resultados del adaptador. El teléfono ignora
integraciones desconocidas y muestra únicamente las que reconoce.

Los comandos pueden incluir además una lista `parameters` de metadatos no
sensibles. Una lista vacía significa que la acción no tiene argumentos y puede
ejecutarse directamente por el cliente actual; si el campo falta, el cliente
conserva el camino compatible de frase libre. Cada entrada solo contiene
`name`, `label`, `kind`, `max_length` y, opcionalmente, una lista corta de
`options` allowlisted:

```json
{
  "id": "league_search",
  "tool_name": "league_search",
  "phrase": "busca una partida <cola>",
  "description": "Inicia matchmaking en una cola allowlisted.",
  "safety": "unsafe",
  "requires_confirmation": true,
  "parameters": [
    {
      "name": "queue",
      "label": "Cola",
      "kind": "queue",
      "max_length": 32,
      "options": ["aram", "normal_draft", "ranked_solo"]
    }
  ]
}
```

La UI Swift valida esos metadatos y, cuando están presentes, ofrece un
formulario local y envía un `tool_call` estructurado cifrado. Los valores no se
guardan en el catálogo ni se devuelven en confirmaciones. El iPhone añade
`request_digest`, un SHA-256 del JSON canónico `{name, arguments}`. El Core lo
recalcula antes de llamar al router y lo conserva en la confirmación sin
exponer los argumentos. La respuesta `confirm_request` devuelve solo ese
digest; el iPhone bloquea `Aceptar` si falta o no coincide con su vista local.
Así un cambio de teléfono, mensaje, canal, cola o URL no puede quedar oculto
tras una confirmación del mismo tipo de herramienta. Si un agente antiguo no
publica `parameters`, la UI conserva el camino compatible de frase libre.
El Core vuelve a validar ese contrato —incluidos campos extra, tipos, límites y
allowlists— antes de crear una confirmación y al consumirla.

Para ayudar a la revisión humana, la UI Swift puede mostrar además una copia
efímera del comando que el usuario acaba de preparar en el propio teléfono.
Esa vista local nunca forma parte de `confirm_request`, no se persiste y se
borra al resolver la confirmación, cerrar la sesión o fallar la operación. En
comandos estructurados, si la herramienta o el digest de argumentos solicitado
por el agente no coincide con la selección local, la UI bloquea `Aceptar` y
solo permite rechazarla.

Una acción directa que no muestra marcadores pero necesita argumentos fijos puede
publicar además `default_arguments`, un objeto pequeño de textos acotados. Solo
se acepta junto a `parameters: []`; la UI valida esos valores y los envía sin
permitir que el usuario los edite. Por ejemplo, los botones de reproducción,
anterior, siguiente y detener usan la herramienta común `media_action` con una
acción fija. Este campo no sirve para transportar configuración privada ni datos
de la persona.

```json
{
  "id": "media_next",
  "tool_name": "media_action",
  "phrase": "siguiente canción",
  "description": "Pasa a la siguiente pista.",
  "safety": "safe",
  "requires_confirmation": false,
  "parameters": [],
  "default_arguments": {"action": "next"}
}
```

Los cuerpos de mensaje pueden contener saltos de línea únicamente en el campo
tipado `message`; los controles y formatos invisibles siguen rechazándose.

El teléfono envía primero:

```json
{
  "protocol_version": 1,
  "type": "device_hello",
  "firmware_version": "pipa-ios-<version>",
  "capabilities": ["display", "touch", "mobile", "text_input"]
}
```

No se debe anunciar `display` o `touch` si la aplicación no puede mostrar el
resumen y recibir una confirmación visible. No se debe anunciar audio hasta
que exista un diseño de captura, cifrado, indicador de escucha y borrado.

## Acciones y privacidad

Las acciones externas reciben `confirm_request` y nunca se ejecutan en el
primer `tool_call`. La aplicación móvil debe mostrar el resumen, permitir
aceptar o rechazar y enviar el identificador exacto una sola vez.
El campo `summary` que cruza el transporte es una etiqueta fija allowlisted
por herramienta: no interpola el teléfono, mensaje, URL, contacto, ID de canal
ni cola concreta de los argumentos. El resumen detallado solo permanece en el
flujo local del agente; la revisión final del destino se hace en la aplicación
que se abre.

El resultado físico es deliberadamente pequeño:

```json
{
  "protocol_version": 1,
  "type": "tool_result",
  "tool_name": "web_search",
  "status": "completed",
  "success": true
}
```

No se entregan al teléfono URLs privadas, textos de WhatsApp, tokens de
League, memoria del Core ni datos crudos de los adaptadores. La UI puede
recibir además un caption breve y allowlisted en `ui_state` —por ejemplo,
porcentaje de batería, si League está buscando, si hay una partida pendiente de
aceptación o el número de temporizadores—
pero nunca recibe nombres de interfaces, IDs, etiquetas, contactos o mensajes.
WhatsApp sigue requiriendo pulsar `Enviar`, Discord sigue requiriendo iniciar
la llamada, League sigue requiriendo aceptar la partida y el Apple Music remoto
sigue requiriendo elegir la pista. La app
iOS también puede ofrecer una ruta local independiente basada en MusicKit: esa
ruta solicita permiso del sistema y reproduce en el iPhone, sin enviar la
búsqueda por este transporte ni cambiar las confirmaciones del agente.

## Transporte TCP v2 opt-in

El transporte implementado está en `windows-agent/secure_tcp_gateway.py` y
`windows-agent/secure_mobile_tcp_client.py`. Solo se activa cuando se
configuran explícitamente todas estas variables de usuario:

```powershell
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_TRANSPORT', 'tcp-v2', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_BIND', '192.168.1.20', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_PORT', '18765', 'User')
```

`PIPA_MOBILE_BIND` debe ser una IPv4 privada/link-local concreta del PC o
`127.0.0.1` para pruebas. `::1` se admite solo para loopback; no se aceptan
`0.0.0.0`, `::`, IPv6 de LAN, direcciones públicas ni una ausencia de puerto.
El agente carga la identidad protegida por DPAPI y únicamente las claves de
`HKLM\SOFTWARE\Pipa\Mobile\Devices`; no crea identidades al
arrancar y no comparte el almacén con Trusted Unlock. El canal cierra sin
fallback si el primer mensaje no es `ClientHello`, si falla el handshake, si
hay un frame inválido o si se supera el límite de conexiones.

Antes de probar una app real, el diagnóstico reproducible es:

```powershell
python .\windows-agent\pipa_cli.py mobile-tcp-test
python .\windows-agent\pipa_cli.py mobile-config
```

Ese comando abre únicamente un puerto efímero en loopback, verifica el
handshake cifrado, catálogo, confirmación y redacción del resultado, y lo
cierra al terminar. El cliente Python no es una app iPhone ni sustituye la
revisión de CryptoKit y del almacén seguro de iOS.

`mobile-config` es independiente del listener: valida el modo, la IP, el
puerto, el identificador del servidor, la identidad protegida y, cuando
Windows lo permite, que exista al menos un dispositivo móvil emparejado. La
lectura del almacén del Registro es de solo lectura; no añade, elimina ni
modifica dispositivos. La salida no incluye la IP completa, la ruta local,
los IDs ni las claves.

El firewall tampoco se modifica automáticamente. Cuando haya que probar desde
el iPhone, `scripts/configure_mobile_firewall.ps1` ofrece una regla reversible
con `-WhatIf`, perfil `Private`, IP local exacta y origen `LocalSubnet` o una
IPv4 privada concreta. No se debe usar una regla pública ni port-forwarding.

## Integración iOS que aún falta para producto móvil

El transporte TCP v2 ya tiene un cliente Swift, una UI de referencia y un
gateway Windows opt-in. Para convertirlo en producto distribuible aún falta
validar el binario en Xcode/iPhone, integrar firma/provisioning y completar la
operación de actualización. La aplicación final debe cumplir como mínimo:

- listener desactivado por defecto y sin comodines de escucha;
- conexión solo a la IP privada concreta configurada por el usuario, sin
  port-forwarding ni endpoints públicos;
- enrolamiento explícito, revocación y cierre de sesiones revocadas;
- UI que muestre `confirm_request` y no automatice el último paso de WhatsApp,
  llamadas de Discord o reproducción musical;
- actualización firmada de la app y del agente, con recuperación;
- logs sin cuerpos, claves, tokens ni contactos;
- pruebas de replay, downgrade, clave equivocada, pérdida de red y reloj;
- vector bidireccional Python↔cliente Swift antes de anunciar soporte. El
  record-layer ya tiene un fixture determinista compartido en
  `mobile-ios/Tests/Fixtures/mobile_record_v2.json`. El handshake completo
  también se compara en Python y Swift mediante
  `mobile-ios/Tests/Fixtures/mobile_handshake_v2.json`; sus semillas son
  exclusivamente sintéticas y no deben reutilizarse. Aún falta ejecutar la
  prueba Swift en macOS/iPhone como parte de la validación Apple.

No se debe usar Wake-on-LAN como autenticación ni convertir el endpoint local
actual en un servidor móvil cambiando simplemente el host de escucha.
