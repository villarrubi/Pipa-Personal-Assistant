# Checklist de validación iOS

Esta lista valida el cliente remoto sin convertirlo en un mecanismo de
desbloqueo. La app debe mantener contraseña, PIN y Windows Hello como métodos
de recuperación.

## 1. Compilación en Mac

- Abrir `mobile-ios/PipaMobileApp/PipaMobile.xcodeproj` en Xcode sobre macOS.
- Confirmar que el esquema compartido `PipaMobile` aparece disponible y que
  enlaza el paquete local del repositorio.
- Confirmar que el target usa `mobile-ios/App/Info.plist`, conserva
  `NSLocalNetworkUsageDescription`, `NSMicrophoneUsageDescription` y
  `NSSpeechRecognitionUsageDescription`, y no añade dominios públicos ni
  excepciones ATS genéricas.
- Ejecutar las pruebas del paquete en un simulador iOS 16 o posterior.
- Confirmar que no hay warnings de concurrencia, Keychain, Network o CryptoKit
  que se estén ignorando.
- Confirmar que una IP inalcanzable, un firewall bloqueado o una sesión sin
  respuesta termina por timeout de conexión/I/O y devuelve la pantalla a
  `Desconectado`, sin dejar una tarea pendiente.
- No distribuir el binario mientras las pruebas Swift no pasen en limpio.

El equipo Windows del repositorio no tiene Xcode ni Swift, por lo que su
preflight solo comprueba estructura y controles estáticos.

## 2. Provisioning del agente

En Windows, preparar la identidad del agente y conservar solo la clave pública:

```powershell
python .\windows-agent\secure_identity_admin.py init
python .\windows-agent\secure_identity_admin.py show
```

En el iPhone:

- crear/cargar la identidad con `PipaKeychainIdentityStore`;
- mostrar el fingerprint en pantalla completa;
- comparar el fingerprint por un canal local con el PC;
- ejecutar desde la raíz del repositorio, solo después de la comparación:

  ```powershell
  python .\windows-agent\trusted_unlock_admin.py pair-mobile `
    --device-id iphone-main `
    --public-key <CLAVE_PUBLICA_BASE64URL> `
    --expected-fingerprint <FINGERPRINT_COMPARADO>
  ```

- fijar el `server_id` y la clave pública del agente en la configuración de la
  app, nunca descubiertos desde la red.

## 3. Transporte privado

Configurar en Windows una IP privada concreta y un puerto explícito:

```powershell
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_TRANSPORT', 'tcp-v2', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_BIND', '192.168.1.20', 'User')
[Environment]::SetEnvironmentVariable('PIPA_MOBILE_PORT', '18765', 'User')
```

- No usar `0.0.0.0`, `::`, port-forwarding ni una IP pública.
- Confirmar firewall solo para la red privada bajo control del usuario.
- Verificar que el listener no existe si falta provisioning, emparejamiento o
  configuración completa.
- Comprobar que una revocación en Windows cierra la sesión iOS activa.

## 4. Primera sesión sin efectos

- Conectar y comprobar `device_hello_ack`.
- Pedir el catálogo y confirmar que no contiene URLs, rutas, tokens,
  contactos ni resultados de herramientas.
- Abrir un comando con `parameters`, comprobar que el formulario muestra solo
  etiquetas, tipos, límites y opciones allowlisted, y que `Enviar acción
  estructurada` convierte un entero/cola en el tipo correcto.
- Probar un mensaje de WhatsApp con un salto de línea: debe viajar solo como
  argumento cifrado, no aparecer en `confirm_request` y seguir requiriendo
  pulsar `Enviar` en WhatsApp.
- Ejecutar primero `system_status` o `league_status`.
- Comprobar que un `tool_call` externo solo produce `confirm_request`.
- Rechazar una confirmación y comprobar que no se abre ninguna aplicación.
- Aceptar una acción sintética y comprobar que el dispositivo recibe solo el
  sobre de estado y `ui_state`, nunca el resultado interno.
- Probar replay, frame alterado, clave de servidor incorrecta, downgrade y
  cierre de red.
- Probar que dos peticiones simultáneas desde tareas distintas se serializan o
  reciben `requestInProgress`, sin entrelazar frames.

## 5. Integraciones reales

Validar una por una, siempre con confirmación visible:

- web: abre una búsqueda acotada;
- Apple Music: abre resultados, pero la pista se selecciona manualmente;
- WhatsApp: prepara el chat, pero el usuario pulsa `Enviar`;
- Discord: abre el canal, pero el usuario inicia la llamada;
- League: una búsqueda confirmada puede abrir el cliente si está cerrado y
  espera un tiempo acotado; la cola sigue allowlisted y cancelar requiere que
  el cliente ya esté listo.

## 6. Dictado local del iPhone

- Conceder micrófono y reconocimiento de voz solo durante la primera prueba;
  comprobar que el texto aparece en el editor y no se envía automáticamente.
- Confirmar que el código exige `requiresOnDeviceRecognition` y que un iPhone
  sin reconocimiento local disponible falla cerrado, sin activar un proveedor
  remoto por sorpresa.
- Poner la app en segundo plano durante el dictado y comprobar que el audio se
  detiene; borrar la transcripción si se pulsa cancelar.
- Para el Waveshare, no añadir todavía audio, STT, llamadas automáticas, envío
  automático ni playback automático: esa ruta sigue pendiente de validar el
  hardware, el consentimiento y el transporte protegido.
