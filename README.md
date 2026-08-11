# Pipα — asistente personal local

Pipα es un asistente para Windows con un agente local, un núcleo de comandos
confirmables y firmware para el **Waveshare ESP32-S3-Touch-LCD-1.85C-BOX
(SKU 30684)**. El diseño prioriza funcionamiento local, permisos mínimos y
recuperación segura.

## Estado real

| Componente | Estado |
| --- | --- |
| Windows Agent | Operativo en `127.0.0.1:8765`, con inicio oculto y log local rotativo |
| Comandos de PC | Operativos: apps, web, música, audio, multimedia, temporizadores, League, WhatsApp y Discord |
| Núcleo Pipα | Operativo: sesiones, Ed25519, estados de UI, herramientas y confirmaciones |
| Gateway Waveshare | Implementado por USB CDC; requiere configurar el futuro puerto COM |
| Firmware SKU 30684 | Compila para ESP32-S3 N16R8; aún no se ha probado en la placa física |
| Pantalla, micrófono y altavoz | Pendientes de validar e integrar con el hardware real |
| Voz | El protocolo acepta texto reconocido; todavía no hay STT ejecutándose en el Waveshare |
| Wake-on-LAN | Implementado en firmware; pendiente de prueba física y configuración de BIOS/red |
| Trusted Unlock | **Desactivado**: la tile existe, pero no autentica ni entrega credenciales a Windows |
| iPhone/remoto | No existe acceso remoto seguro; Wake-on-LAN del móvil depende de la red y de la app usada |

Pipα no sustituye ni desactiva contraseña, PIN, Windows Hello u otros
Credential Providers. Hoy no permite entrar en Windows sin uno de esos métodos.

## Arquitectura

```text
Waveshare --USB JSON + firma Ed25519--> Gateway serie
                                               |
iPhone futuro --transporte aún no diseñado--> Pipα Core --> herramientas Windows
                                               |                 |
                                               |                 +--> confirmación si sale del PC
                                               +--> sesión temporal

Credential Provider --> broker local experimental --> siempre unlock_enabled=false
```

El agente HTTP y WebSocket solo escucha en loopback. El dispositivo se
autentica mediante desafíos de un solo uso; las acciones externas se ligan a
la sesión que las solicitó y caducan si no se confirman.

## Qué puedes usar sin hardware

- Abrir aplicaciones configuradas localmente y bloquear el PC.
- Buscar en Internet y abrir búsquedas de Apple Music.
- Controlar volumen y teclas multimedia.
- Crear y consultar temporizadores en memoria.
- Abrir League y comenzar/cancelar matchmaking en colas permitidas si el
  cliente ya está abierto y autenticado.
- Preparar un mensaje de WhatsApp sin pulsar `Enviar`.
- Abrir un canal de Discord sin iniciar automáticamente una llamada.
- Probar todo el protocolo de dispositivo con un simulador efímero.
- Compilar el firmware exacto sin tener la placa.

Consulta el catálogo y sus límites en
[windows-agent/README.md](windows-agent/README.md).

## Instalación del agente

Desde PowerShell en la raíz:

```powershell
python -m venv .\windows-agent\.venv
.\windows-agent\.venv\Scripts\python.exe -m pip install `
  -r .\windows-agent\requirements.txt
```

Inícialo manualmente y comprueba el estado:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\start_agent_hidden.ps1

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\check_agent_status.ps1
```

Para arrancarlo al iniciar sesión, ejecuta una vez PowerShell como
administrador:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\install_agent_task.ps1
```

El agente no deja una ventana CMD abierta. Su log está en
`%LOCALAPPDATA%\Pipa\logs\agent.log`, rota a 1 MB y conserva dos copias.

## Validación

```powershell
python -B -m unittest discover -s backend/tests -p "test_*.py"
python -B -m unittest discover -s windows-agent/tests -p "test_*.py"
python -m compileall -q backend windows-agent

.\scripts\check_repo_hygiene.ps1
.\scripts\check_git_history.ps1
```

La CI repite esas comprobaciones, ejecuta Ruff, audita dependencias, compila
el firmware y construye/prueba el Credential Provider x64.

Para compilar el firmware:

```powershell
python -m venv .\firmware\.venv
.\firmware\.venv\Scripts\python.exe -m pip install platformio==6.1.19
.\firmware\.venv\Scripts\pio.exe run -d firmware -e waveshare-185c
```

## Cuando llegue el Waveshare

Solo quedará trabajo dependiente del dispositivo:

1. confirmar revisión de placa, pines y controladores de pantalla/audio;
2. cargar el firmware y comprobar USB, touch, Wi‑Fi y Wake-on-LAN;
3. comparar físicamente la huella de la clave antes de emparejarla;
4. implementar UI, captura de audio y STT sobre el protocolo ya probado;
5. validar Secure Boot, cifrado de Flash, actualización y recuperación;
6. revisar de nuevo el modelo de amenazas antes de plantear desbloqueo real.

## Seguridad y privacidad

Las configuraciones con rutas, Wi‑Fi, MAC o puertos viven en archivos locales
ignorados. No deben entrar en Git claves privadas, tokens, builds, logs,
capturas de LogonUI ni datos personales. Los controles y limitaciones están
documentados en [SECURITY.md](SECURITY.md).

## Estructura

```text
Pipa/
├── backend/          protocolo, sesiones, memoria temporal y simulador
├── firmware/         firmware PlatformIO y definición de la placa N16R8
├── scripts/          comprobaciones de higiene actual e histórica
├── trusted-unlock/   Credential Provider experimental y rollback
└── windows-agent/    API local, herramientas, gateway USB y arranque oculto
```
