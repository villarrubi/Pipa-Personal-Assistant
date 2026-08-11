# Seguridad de Pipα

## Estado de seguridad

Pipα está en desarrollo. El Credential Provider actual es una tile adicional
de prueba y no desbloquea Windows: `GetSerialization` no entrega credenciales.
No se considera todavía un producto de autenticación listo para producción.

## Límites que no se deben romper

- No guardar contraseñas, PIN, tokens estáticos ni claves privadas en el PC o
  en el repositorio.
- No desactivar contraseña, PIN, Windows Hello ni otros Credential Providers.
- No exponer el Windows Agent en una interfaz de red pública.
- No añadir un endpoint HTTP que desbloquee Windows.
- No convertir el broker experimental en un servicio privilegiado ni activar
  el desbloqueo antes de completar las pruebas de IPC, ACL y recuperación.
- No generar una serialización de Windows sin una revisión de seguridad y un
  procedimiento de recuperación probado.
- No registrar dispositivos sin una confirmación explícita y verificable de su
  fingerprint.

## Datos que nunca deben entrar en Git

- Claves privadas, certificados, tokens, archivos `.env` y credenciales.
- Builds, dumps, logs y artefactos de Visual Studio/CMake.
- Configuraciones locales con rutas, nombres de usuario, IPs o dispositivos.
- Capturas de pantalla de LogonUI que puedan mostrar información personal.

El `.gitignore` evita nuevas inclusiones. Si un dato ya llegó a la historia de
Git o al repositorio remoto, ignorarlo después no lo elimina: hay que hacer una
limpieza histórica coordinada y revisar cualquier push forzado.

## Modelo de amenazas mínimo

Cada fase debe probar al menos:

1. un proceso local no autorizado intentando usar el IPC;
2. replay de una respuesta válida y de un ticket consumido;
3. dispositivo revocado;
4. Registro o DLL ausentes o modificados;
5. broker apagado, reinicio y reloj incorrecto;
6. recuperación mediante el método normal de Windows.

El broker actual usa un Named Pipe con acceso para el usuario de la sesión y
`SYSTEM`, además de exigir una firma Ed25519 del dispositivo emparejado para
crear un ticket. Un proceso que comparta la misma cuenta de Windows puede
intentar hablar con el pipe; por eso la firma del dispositivo sigue siendo la
autorización real. Los tickets son de un solo uso y el broker informa siempre
`unlock_enabled = false`.

## Reportar problemas

No publiques detalles sensibles en issues públicos. Conserva el contenido
mínimo necesario, elimina rutas y tokens, y describe primero el impacto, las
condiciones y los pasos de reproducción.
