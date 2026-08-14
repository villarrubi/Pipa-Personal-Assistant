# Pipα Trusted Unlock — protocolo inicial

## Alcance de esta fase

Esta fase implementa únicamente el núcleo criptográfico de un flujo de
autorización. No desbloquea Windows, no genera credenciales para LogonUI y no
añade ninguna ruta HTTP de desbloqueo.

La implementación está en `windows-agent/trusted_unlock_protocol.py` y usa
firmas Ed25519. El dispositivo autorizado conserva la clave privada; el PC
solo necesita conocer la clave pública asociada al dispositivo.

## Flujo previsto

1. Durante un emparejamiento explícito, el dispositivo genera su par de claves.
2. El PC registra el `device_id` y la clave pública. La clave privada nunca se
   guarda en el repositorio ni se envía al agente.
3. El verificador genera un desafío con `challenge_id`, nonce aleatorio de 32
   bytes, operación, audiencia, versión y caducidad corta.
4. El dispositivo firma la representación JSON canónica completa del desafío.
5. El verificador comprueba que el desafío fue emitido por él, que no caducó,
   que el dispositivo sigue autorizado y que la firma es válida.
6. El desafío se consume una sola vez. Una respuesta repetida se rechaza.
7. En una fase posterior, una autorización aceptada podrá entregarse al
   Credential Provider mediante IPC local protegido. Todavía no se hace.

La implementación ya incluye un ticket interno de una sola operación en
`windows-agent/trusted_unlock_ticket.py`. El ticket es un identificador opaco
de vida muy corta y se prueba de forma aislada, pero el broker en ejecución
está en modo `health-only` mientras `unlock_enabled=false`: no crea desafíos,
no emite tickets y no los consume. Así, ninguna integración futura puede
confundir una autorización experimental con permiso de inicio de sesión.

La firma cubre todos los campos del desafío. Por tanto, no se puede cambiar la
operación, el dispositivo, el nonce o la caducidad sin invalidar la firma.

Los identificadores estructurales (`device_id`, `challenge_id`, operación,
audiencia, `request_id` y comandos del broker) usan una gramática ASCII
acotada; no aceptan controles Unicode, bidi ni caracteres invisibles.

## Estado de seguridad actual

El broker local usa una ACL limitada al usuario interactivo y `SYSTEM`,
rechaza clientes remotos y solicita `FILE_FLAG_FIRST_PIPE_INSTANCE`; si otro
proceso ocupa el nombre del pipe, el broker falla en lugar de conectarse a él.

- No existe `/unlock` ni otro endpoint que desbloquee Windows.
- `GetSerialization` del Credential Provider sigue sin entregar credenciales.
- No se almacena ninguna contraseña, PIN, token estático o secreto compartido.
- Los desafíos caducan como máximo en 60 segundos; el valor normal es 30.
- El número de desafíos pendientes está acotado globalmente y por dispositivo.
- La caché de desafíos consumidos y la de tickets consumidos están limitadas a
  4.096 entradas cada una; expulsar una entrada antigua no permite reutilizarla,
  porque el replay pasa a rechazarse como identificador desconocido.
- Un dispositivo revocado no puede completar desafíos pendientes.
- El estado pendiente y anti-replay vive en memoria y se pierde al reiniciar;
  esto hace que los desafíos antiguos fallen cerradamente.
- Los tickets internos duran como máximo 10 segundos y solo pueden consumirse
  una vez.
- El cliente del pipe valida también las respuestas: rechaza JSON duplicado,
  campos desconocidos, sobres con forma incorrecta y errores con texto no
  acotado antes de entregar un resultado al proceso llamador.
- El cliente usa una llamada Named Pipe con tiempo límite para toda la
  petición/respuesta; no deja una lectura bloqueada indefinidamente. El broker
  cierra solo la conexión que envía un mensaje mayor que el límite y mantiene
  vivo su bucle de servicio.
- Mientras Trusted Unlock siga desactivado, el broker solo responde a
  `health`; cualquier otra operación devuelve `unlock_disabled` sin mutar su
  estado pendiente.

## Emparejamiento y revocación

El almacén persistente de Windows usa únicamente:

```text
HKLM\SOFTWARE\Pipa\TrustedUnlock\Devices\<device_id>
```

Cada entrada contiene la clave pública Ed25519 en base64url y su fecha de
registro. La modificación requiere una consola elevada. La clave privada del
teléfono o hardware no debe pasar nunca por este comando ni guardarse en el PC.

La herramienta administrativa se ejecuta desde la carpeta `windows-agent`:

```powershell
cd .\windows-agent

# Ver dispositivos emparejados
python .\trusted_unlock_admin.py list

# Emparejar una clave pública proporcionada por el dispositivo, tras comparar
# físicamente su fingerprint
python .\trusted_unlock_admin.py pair --device-id phone-main --public-key <CLAVE_PUBLICA_BASE64URL> --expected-fingerprint <FINGERPRINT_COMPARADO>

# Revocar de forma explícita
python .\trusted_unlock_admin.py revoke --device-id phone-main --yes
```

El almacén rechaza reemplazar una clave existente para el mismo `device_id`.
El `fingerprint` mostrado sirve para comparar el emparejamiento por un canal
independiente.

## Lo que falta antes de una integración real

- Revisar de forma independiente el emparejamiento, Registro y ACL del pipe.
- Ejecutar el broker con lifecycle controlado, identidad de proceso verificable
  y actualización segura; hoy sigue siendo experimental.
- Integrar el ticket con el Credential Provider sin habilitar serialización y
  someter el IPC a pruebas adversarias.
- Diseñar la serialización que Windows espera sin almacenar contraseña/PIN ni
  alterar los métodos normales de inicio de sesión.
- Validar Secure Boot, cifrado de Flash, anti-rollback y recuperación física
  del dispositivo.
- Probar reinicios, pérdida del dispositivo, corrupción y rollback en una
  máquina de ensayo antes de activar autenticación alguna.

## Referencia criptográfica

Ed25519 es la instancia de EdDSA descrita en [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html).
La implementación Python utiliza la API de firmas y verificación de
`cryptography`; no implementa las operaciones matemáticas por cuenta propia.
