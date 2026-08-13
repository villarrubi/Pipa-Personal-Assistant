# Pipa Secure Session v2 (opt-in)

El transporte actual v1 autentica el dispositivo mediante un reto Ed25519,
pero sus líneas JSON no están cifradas. Por eso v1 solo se usa en el canal USB
local y no transporta audio, secretos ni credenciales.

Este documento define la siguiente capa. Está implementada para el agente
Python y el firmware, pero permanece opt-in: el transporte v1 sigue siendo el
valor predeterminado hasta validar la placa física, provisionar la identidad
del agente y completar las pruebas de interoperabilidad.

## Intercambio

1. El cliente genera una clave X25519 efímera y un nonce de 32 bytes.
2. Envía `ClientHello` con su `identity_id`, clave efímera, nonce y una firma
   Ed25519 sobre todos esos campos y `role=client`.
3. El agente verifica la firma con la clave pública emparejada, genera su
   propia clave X25519 efímera y nonce, y responde con `ServerHello`.
4. `ServerHello` contiene ambos extremos, firma el transcript completo con la
   identidad Ed25519 del agente y queda asociado a `session_id`.
5. El cliente comprueba tanto la firma como el `server_id` esperado de la
   identidad provisionada. Ambos derivan 32 bytes de clave por dirección y un prefijo de nonce de 4
   bytes mediante HKDF-SHA256. Cada registro usa ChaCha20-Poly1305 con un
   contador de 64 bits y autentica también la cabecera.

El servidor debe tener una identidad Ed25519 propia y el cliente debe conocer
su clave pública. El código no acepta una clave de servidor descubierta por el
canal. Las claves efímeras y de sesión solo viven en memoria; al cerrar una
sesión no se reutilizan sus contadores.

## Estado

- Implementado y probado en Python: handshake mutuo, derivación direccional,
  autenticación de cabecera, AAD opcional, límites de tamaño, orden estricto,
  replay y cierre fail-closed.
- Record layer equivalente disponible en
  `firmware/src/pipa_secure_session.cpp`, usando `rweather/Crypto`
  (`ChaChaPoly` y `HKDF`). El intercambio X25519 y la negociación de mensajes
  del cliente están en `firmware/src/pipa_secure_handshake.cpp` y se conectan
  condicionalmente mediante `PipaSecureProtocol` cuando
  `PIPA_SECURE_SESSION_ENABLED=1`.
- El adaptador Python `windows-agent/secure_session_server.py` valida el
  `ClientHello`, selecciona únicamente una clave Ed25519 ya emparejada y crea
  el `ServerHello` sin escuchar en red ni guardar claves. Es una pieza de
  transporte, no una activación del agente.
- `windows-agent/secure_json_channel.py` cifra objetos JSON con AAD fija
  `pipa/json/v2`, rechaza campos duplicados, arrays, `NaN`, payloads grandes y
  sobres de transporte con campos extra. El contenido del Core sigue siendo
  validado por el parser v1 después de descifrarlo.
- Las claves, firmas, nonces y ciphertexts usan base64url sin padding y con
  bits residuales canónicos; ambos extremos rechazan codificaciones
  alternativas que representarían los mismos bytes.
- El firmware también cierra el estado seguro completo ante una trama cifrada
  inválida, alterada, fuera de secuencia o con JSON ilegible; borra la sesión y
  espera un nuevo handshake, sin conservar una sesión parcialmente autenticada.
  También reinicia el handshake si el Core informa que la sesión autenticada
  ya no existe o que la autenticación dejó de ser válida.
- `windows-agent/secure_core_connection.py` conecta ese canal, solo en memoria,
  con el lifecycle de `PipaCore`: crea y limpia la sesión del dispositivo,
  procesa el parser de comandos y devuelve respuestas cifradas. No está
  registrado como ruta FastAPI ni como WebSocket activo.
- Tras completar el handshake, el firmware envía un `device_hello` cifrado con
  su versión y capacidades físicas. El Core crea la sesión v2 sin capacidades
  de confirmación y solo las habilita una vez recibido ese anuncio. Mientras
  tanto, únicamente acepta `ping`, `device_status` y `abort`; catálogo, texto,
  órdenes y confirmaciones devuelven `device_hello_required` sin crear
  pendientes ni ejecutar handlers. Omitirlo o repetirlo no permite ejecutar
  acciones externas.
- `windows-agent/secure_serial_gateway.py` conecta ese adaptador al USB serie
  cuando `PIPA_SERIAL_SECURITY=v2`. Es una selección explícita: tras recibir
  un ClientHello v2, una línea v1, un JSON duplicado o un error de autenticación
  cierra la conexión y no intenta continuar en v1. Aplica además timeout de
  handshake de 20 segundos e inactividad autenticada de 10 minutos. Solo
  carga una identidad DPAPI ya provisionada; nunca crea una identidad durante
  el arranque. La caché anti-replay de `session_id` está limitada a 4.096
  entradas y 30 minutos. El gateway v1 sigue siendo el valor predeterminado
  mientras el firmware físico no tenga activado v2.
- `windows-agent/secure_identity_store.py` ofrece el provisioning local de la
  identidad privada del agente usando DPAPI de Windows. Su ruta por defecto
  está fuera del repositorio; `secure_identity_admin.py init` la crea y el
  gateway v2 solo la carga, mientras que el agente v1 no la toca.
- El vector determinista está duplicado en la prueba Python y en
  `PipaSecureSession::vectorSelfTest()`. El entorno PlatformIO
  `secure-session-vector` compila el ejecutable que lo mostrará como `PASS` al
  arrancar una placa de pruebas; sin hardware, esa última ejecución física no
  se puede afirmar todavía.
- El canal seguro puede transportar las mismas órdenes del Core que el canal
  v1, por lo que las confirmaciones y límites de WhatsApp, Discord, Apple
  Music y League se mantienen. No concede permisos nuevos ni conecta el
  transporte con Trusted Unlock o Winlogon.
- `windows-agent/secure_mobile_client.py` implementa un cliente de referencia
  en memoria y `secure_mobile_tcp_client.py` prueba el mismo flujo sobre TCP
  real en loopback. Ninguno persiste claves y ninguno es una aplicación
  iPhone.
- `windows-agent/secure_tcp_gateway.py` implementa el listener TCP v2, pero
  permanece desactivado por defecto: exige `PIPA_MOBILE_TRANSPORT=tcp-v2`, una
  IP privada concreta, un puerto explícito, identidad DPAPI y al menos una
  clave del almacén móvil. El contrato y los requisitos de enrolamiento,
  revocación, actualización y red están en `MOBILE_PROTOCOL.md`.

No se debe marcar como cifrado el producto hasta que los vectores de prueba
Python↔firmware y Python↔cliente móvil pasen en ambos sentidos.
