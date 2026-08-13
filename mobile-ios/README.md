# PipaMobileCore

Paquete Swift para la aplicación iPhone de Pipα. Implementa el contrato TCP v2
con CryptoKit, Network y Keychain del sistema, además de una UI SwiftUI mínima
en `PipaMobileUI` para conectar, consultar el catálogo, dictar localmente un
comando, enviar texto y resolver confirmaciones visibles. No habilita el
transporte en Windows por sí mismo.

La secuencia de aceptación para Xcode, provisioning, transporte e integraciones
está en [ARRIVAL_CHECKLIST.md](ARRIVAL_CHECKLIST.md). El repositorio incluye
además un proyecto Xcode listo para abrir en
`PipaMobileApp/PipaMobile.xcodeproj`.

## Uso previsto

1. Abrir `mobile-ios/PipaMobileApp/PipaMobile.xcodeproj` en Xcode sobre macOS.
   El proyecto ya enlaza el paquete local, añade `App/PipaMobileApp.swift` y
   usa el `App/Info.plist` rastreado con las declaraciones de red, micrófono y
   reconocimiento. Seleccionar un Team de firma en el target antes de ejecutar
   en un iPhone; para un simulador basta con desactivar la firma automática si
   Xcode la solicita.
2. Generar o cargar la identidad Ed25519 mediante `PipaKeychainIdentityStore`.
3. Pulsar “Preparar identidad”, mostrar la clave pública y fingerprint y
   ejecutar `pair-mobile` en el PC solo después de compararlo físicamente.
4. Fijar manualmente `server_id` y la clave pública Ed25519 del agente.
   La UI calcula y muestra también el fingerprint de esa clave para compararlo
   por un canal fuera de banda antes de conectar. La UI exige marcar esa
   comparación explícitamente; la marca es temporal y no se guarda en Keychain.
5. Conectar solo a una IP literal loopback, privada o link-local y al puerto
   configurado por el usuario; el cliente rechaza DNS, comodines y direcciones
   públicas.
6. Mostrar `confirm_request` en una UI visible y enviar `confirm` una sola vez.

Para comprobar el proyecto sin firmar una aplicación:

```bash
xcodebuild -project mobile-ios/PipaMobileApp/PipaMobile.xcodeproj \
  -scheme PipaMobile -sdk iphonesimulator \
  -configuration Debug CODE_SIGNING_ALLOWED=NO build
```

Tras conectar, la app muestra también una matriz resumida de integraciones
(`Disponible`/`No disponible`) y sus pasos manuales para el PC: Apple Music
requiere seleccionar la pista y permite controlar reproducción/pausa del
reproductor activo, WhatsApp requiere pulsar `Enviar` y Discord requiere
iniciar la llamada. Esa matriz contiene solo flags y textos acotados, nunca
configuración del PC.

La pantalla incluye además una sección independiente de Apple Music local para
el propio iPhone. Al pulsar `Autorizar Apple Music`, MusicKit solicita el
permiso del sistema; después `Buscar canciones` muestra hasta cinco
coincidencias y solo reproduce la que pulses en la lista. Los botones de pausa
y siguiente actúan solo sobre ese reproductor. Esta ruta no
envía la búsqueda al PC, no guarda tokens y no cambia las confirmaciones del
agente Windows. Requiere una cuenta/suscripción compatible y queda pendiente
de validación física en Xcode/iPhone.

Antes de probarla en un dispositivo, usa un Bundle ID explícito para el target
y activa el servicio MusicKit en su App ID desde Certificates, Identifiers &
Profiles de Apple Developer. MusicKit asocia ese servicio al Bundle ID durante
la ejecución; no se debe copiar ninguna clave privada ni token al repositorio.
La guía oficial está en
<https://developer.apple.com/documentation/musickit/integrating-musickit-into-your-app>.

También hay una sección local para WhatsApp y Discord. WhatsApp usa un enlace
HTTPS wa.me para abrir un chat o preparar el texto; Discord usa un enlace
HTTPS al canal o DM. El sistema puede entregar esos enlaces a la app instalada
o abrirlos en Safari. No se usa UI automation ni APIs privadas: WhatsApp
siempre requiere pulsar Enviar y Discord requiere pulsar Llamar. Los campos
permanecen solo en memoria de la pantalla y no se guardan en Keychain.

La lista de comandos incluye un botón `Usar` para preparar una frase sin
enviarla. Las acciones actuales sin parámetros muestran `Ejecutar` y usan el
camino estructurado cifrado; si una acción directa publica `default_arguments`,
la app valida y envía esos argumentos fijos sin convertirlos en campos editables.
Las acciones peligrosas siguen deteniéndose en
la confirmación visible. Si la frase tiene marcadores (`<consulta>`, `<teléfono>`,
`<mensaje>`, `<cola>`, etc.), la UI abre un formulario local y muestra una
vista previa acotada; después copia el resultado al editor para que la persona
lo revise y lo envíe explícitamente. El formulario solo ejecuta cuando se pulsa
su botón explícito de acción estructurada.

Cuando el agente publica metadatos `parameters`, ese mismo formulario ofrece
también `Enviar acción estructurada`: valida localmente tipos, límites y
opciones y envía un `tool_call` cifrado, sin depender del parser de frases.
El Core vuelve a validar el contrato antes de crear cualquier confirmación;
las acciones peligrosas siguen mostrando la confirmación visible del agente;
WhatsApp y Discord conservan su último paso manual. Agentes antiguos sin esos
metadatos continúan usando el editor de texto compatible.

En iPhone, `Dictar comando` usa `Speech` y `AVAudioEngine` con
`requiresOnDeviceRecognition`; el resultado solo rellena el editor. La app no
envía, confirma ni conserva audio automáticamente. Si el dispositivo no ofrece
reconocimiento local en español, el dictado falla cerrado y el usuario puede
seguir usando el editor de texto.

La clave privada nunca se exporta ni se incluye en el QR o en el pairing. El
paquete no registra cuerpos de mensajes, URLs, contactos, tokens ni resultados
de herramientas.

La app recuerda la configuración no secreta de conexión (IP privada, puerto,
`server_id`, clave pública fijada e identidad elegida) en un registro Keychain
no sincronizable y accesible solo con el dispositivo desbloqueado. La clave
privada de la identidad usa otro registro independiente; borrar o cambiar la
configuración de conexión no la exporta ni la mezcla con ella.

La UI ofrece `Borrar configuración guardada` para eliminar solo ese registro y
volver a pedir los datos en la siguiente conexión.

## Estado de validación

El código sigue el mismo handshake, canonicalización JSON, HKDF, ChaCha20-
Poly1305, límites y framing que `SECURE_SESSION_PROTOCOL.md`. El record layer
comparte el fixture determinista
`Tests/Fixtures/mobile_record_v2.json` con las pruebas Python. Este entorno es
Windows y no tiene Xcode/Swift SDK, así que la compilación del paquete y las
pruebas en iPhone quedan explícitamente pendientes para un Mac. Hasta que esa
validación exista, no se debe distribuir la app ni activar el transporte TCP
en la LAN. El manifiesto incluye macOS únicamente para que CI pueda ejecutar
las pruebas del núcleo; eso no convierte el cliente en una app de escritorio.

## Límites de seguridad

- Solo TCP v2; no hay fallback al protocolo v1.
- El servidor se valida con una clave pública fijada fuera de banda.
- En iOS, la identidad privada vive en Keychain con `ThisDeviceOnly` y acceso
  al estar desbloqueado el dispositivo. El soporte macOS del paquete existe
  solo para compilar/tests y no es una política de almacenamiento de
  producción.
- Los frames tienen un máximo de 96 KiB y las secuencias son estrictas.
- La conexión inicial tiene un timeout de diez segundos y cada I/O tiene un
  timeout acotado; una recepción vacía o una sesión sin respuesta cierra la
  sesión en vez de dejar la UI esperando indefinidamente.
- El endpoint iOS no permite `0.0.0.0`, `::`, nombres DNS ni hosts públicos;
  esto complementa la validación equivalente del gateway Windows.
- La UI cierra la sesión al pasar a segundo plano y cancela las conexiones
  incompletas para que una sesión vieja no reaparezca como conectada.
- La UI serializa las peticiones, bloquea comandos mientras espera una
  confirmación y destruye la sesión si falla una operación de transporte, para
  que una reconexión no reutilice un cliente roto.
- La UI acepta únicamente los resúmenes fijos definidos por el contrato; un
  servidor que intente incluir argumentos privados en `confirm_request` hace
  fallar la respuesta antes de mostrarla.
- El propio actor TCP también rechaza peticiones concurrentes; la protección no
  depende únicamente de que la UI mantenga deshabilitado el botón.
- El firmware Waveshare todavía no captura audio ni anuncia capacidades de
  voz. El dictado local del iPhone es una función independiente de la UI y no
  cambia el protocolo ni las confirmaciones.
