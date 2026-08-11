# Seguridad de Pipα

## Garantía actual

Pipα está en desarrollo y **no es todavía un producto de autenticación**. El
Credential Provider muestra una tile adicional, pero `GetSerialization` no
entrega credenciales y el broker anuncia siempre `unlock_enabled=false`.
Contraseña, PIN, Windows Hello y los providers normales siguen siendo la vía
de recuperación y acceso.

## Fronteras de confianza

- **API REST local:** automatización para procesos del mismo usuario. Loopback,
  validación de Host, sin CORS, cuerpos acotados y cabecera obligatoria para
  mutaciones. No protege frente a malware que ya se ejecute con la misma
  cuenta.
- **USB/WebSocket de dispositivo:** exige una clave Ed25519 emparejada, desafío
  de un solo uso, sesión temporal y confirmaciones ligadas a sesión.
- **Named Pipe experimental:** ACL para usuario y `SYSTEM`, más firma del
  dispositivo. No desbloquea.
- **Credential Provider:** código cargado por LogonUI; se mantiene separado y
  sin serialización hasta completar revisión y recuperación.
- **Firmware:** la clave vive en NVS. Sin Secure Boot y cifrado de Flash no se
  considera resistente a extracción física.

## Controles implementados

- Ed25519 con JSON canónico; nonce aleatorio de 32 bytes.
- Desafíos de 30 segundos, consumibles una vez y acotados en memoria.
- Revocación de claves públicas y rechazo de reemplazo silencioso.
- Máximo de tres fallos por conexión y rate limit de desafíos.
- Mensajes USB/WebSocket de máximo 12 000 bytes y esquema estricto.
- Timeout de autenticación, inactividad y heartbeat; cleanup al desconectar.
- Confirmaciones de 30 segundos, de un solo uso y ligadas a sesión.
- Herramientas allowlisted y `subprocess` sin shell.
- URLs limitadas a HTTP(S), sin credenciales embebidas.
- Protección contra formularios cross-origin y rechazo de WebSocket de navegador.
- Gateway serie opt-in y sin listener de red.
- Logs locales rotativos que no registran cuerpos, firmas, claves ni tokens.
- CI con tests Python, Ruff, auditoría de dependencias, build de firmware y
  smoke test del Credential Provider.
- Comprobaciones separadas del árbol actual y de toda la historia Git.

## Límites que no se deben romper

- No guardar contraseñas, PIN, cookies, tokens estáticos o claves privadas en
  Windows, logs o Git.
- No enlazar el agente a `0.0.0.0` ni exponerlo mediante port forwarding.
- No añadir `/unlock` HTTP ni aceptar Wake-on-LAN como autenticación.
- No desactivar providers normales ni modificar políticas de recuperación.
- No convertir el broker en servicio privilegiado sin revisar ACL, identidad
  del cliente, lifecycle, actualizaciones y rollback.
- No serializar credenciales en LogonUI sin revisión independiente y pruebas
  de bloqueo/recuperación.
- No emparejar una clave sin comparar su fingerprint físicamente.
- No enviar WhatsApp, iniciar llamadas o ejecutar acciones externas sin la
  confirmación prevista.

## Datos prohibidos en Git

- `.env`, tokens, claves, certificados privados y bases de credenciales.
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
