# Pipα — asistente personal local

Pipα es un prototipo de asistente para Windows que combina un agente local, un
núcleo de comandos confirmables, firmware para el
**Waveshare ESP32-S3-Touch-LCD-1.85C-BOX (SKU 30684)** y un cliente iOS. El
proyecto prioriza el procesamiento local, los permisos mínimos y el fallo
seguro.

> [!WARNING]
> Pipα está en desarrollo. El firmware aún no se ha validado en la placa real,
> el transporte móvil sigue siendo opt-in y Trusted Unlock no desbloquea
> Windows. No lo uses como mecanismo de autenticación ni como firmware de
> producción.

## Estado del proyecto

| Componente | Estado actual |
| --- | --- |
| Windows Agent | Funcional en `127.0.0.1:8765`; arranque oculto por usuario y log local rotativo |
| Núcleo Pipα | Funcional; sesiones, estado de UI, herramientas y confirmaciones |
| Integraciones | Apps, web, Apple Music, multimedia, temporizadores, League, WhatsApp y Discord |
| Gateway Waveshare | Implementado por USB CDC; requiere puerto COM y hardware real |
| Firmware SKU 30684 | Compila para V2 y compatibilidad V1; pantalla, touch y audio pendientes de validación física |
| Cliente iOS | Core, UI SwiftUI, CryptoKit/Keychain y TCP v2 implementados; pendiente de probar en iPhone real |
| Trusted Unlock | Experimental y desactivado; no entrega credenciales ni sustituye PIN, contraseña o Windows Hello |

Las acciones externas conservan una confirmación explícita. WhatsApp funciona
en modo manual por defecto; opcionalmente puede enviar mediante Cloud API tras
configurarlo desde el panel local. Pipα no automatiza el teclado, no inicia
llamadas de Discord, no acepta partidas de League y no selecciona compras ni
pistas automáticamente.

## Qué incluye

- Un agente FastAPI limitado a loopback y una CLI para diagnóstico y uso local.
- Un panel en `http://127.0.0.1:8765/panel` para activar, editar y añadir
  procesos, personalizar frases y configurar automatizaciones locales.
- Un núcleo independiente de transporte con sesiones, confirmaciones de un
  solo uso y resultados redactados.
- Un protocolo v1 autenticado y una sesión v2 cifrada con X25519,
  HKDF-SHA256, Ed25519 y ChaCha20-Poly1305.
- Un gateway TCP móvil v2 desactivado por defecto y restringido a una IP local
  concreta cuando se habilita.
- Firmware PlatformIO para Waveshare V1/V2, vectores criptográficos y pruebas
  host de las partes aislables.
- Un paquete Swift y proyecto Xcode para iOS 16 o posterior.
- Un Credential Provider experimental cuyo `GetSerialization` no entrega
  credenciales.
- CI multiplataforma, auditoría de dependencias, comprobación de secretos e
  historial, y builds de firmware y componentes nativos.

## Arquitectura

```text
Waveshare -- USB CDC + identidad Ed25519 --+
                                             |
iPhone -- TCP v2 cifrado y opt-in ---------> Pipα Core --> herramientas Windows
                                             |                 |
                                             |                 +--> confirmación
                                             +--> sesión temporal

Credential Provider --> broker local experimental --> unlock_enabled=false
```

El REST/WebSocket local solo escucha en loopback. El listener móvil no se crea
si faltan la IP privada concreta, el puerto, la identidad del agente o los
dispositivos emparejados. Ninguno de estos controles protege frente a malware
que ya se ejecute con la misma cuenta de Windows; consulta el modelo de amenaza
en [SECURITY.md](SECURITY.md).

## Requisitos

Para el flujo principal sin hardware:

- Windows 10/11.
- Python 3.12.
- PowerShell 5.1 o PowerShell 7.
- Git.

Opcionales según el componente:

- PlatformIO 6.1.19 para firmware.
- CMake y Visual Studio Build Tools x64 para el Credential Provider.
- macOS con Xcode para compilar la app iOS.
- Waveshare SKU 30684 para las pruebas físicas.

## Inicio rápido sin hardware

Desde PowerShell, en la raíz del repositorio:

```powershell
# Crea windows-agent/.venv, instala dependencias directas fijadas y valida el
# código, pero no registra todavía una tarea de inicio.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\setup_agent.ps1 -SkipTask

# Ejecuta las pruebas inertes contra el código del checkout actual.
.\windows-agent\.venv\Scripts\python.exe `
  .\windows-agent\pipa_cli.py local-self-test

# Inicia el agente local y comprueba su estado.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File .\windows-agent\start_agent_hidden.ps1
.\windows-agent\.venv\Scripts\python.exe `
  .\windows-agent\pipa_cli.py doctor
```

Para revisar lo que haría la instalación completa sin cambiar el sistema:

```powershell
.\windows-agent\setup_agent.ps1 -WhatIf
```

Cuando quieras el inicio automático por usuario, ejecuta
`windows-agent/install_agent_task.ps1`. No necesita elevación y registra una
tarea de nivel limitado; si el Programador de tareas no está disponible, usa
un fallback por usuario documentado en
[windows-agent/README.md](windows-agent/README.md).

## Uso seguro desde la CLI

Estos comandos no necesitan la placa:

```powershell
# Estado agregado y diagnóstico local
python .\windows-agent\pipa_cli.py doctor
python .\windows-agent\pipa_cli.py readiness

# Interpretar o previsualizar sin ejecutar
python .\windows-agent\pipa_cli.py intent "abre WhatsApp para mama"
python .\windows-agent\pipa_cli.py preview "busca una partida de LoL"

# Pruebas inertes de protocolo y cifrado
python .\windows-agent\pipa_cli.py secure-test
python .\windows-agent\pipa_cli.py mobile-tcp-test
python .\windows-agent\pipa_cli.py integration-protocol-test
```

Las acciones externas lanzadas desde la CLI exigen `--confirm`. Los alias,
rutas de aplicaciones, teléfonos, IDs, claves e identidades privadas se
guardan en archivos locales ignorados por Git. Los ejemplos seguros están en
`windows-agent/config/*.example.json`.

El catálogo completo de comandos, frases, límites e integraciones está en
[windows-agent/README.md](windows-agent/README.md).

## Validación

Activa una vez los hooks locales del repositorio:

```powershell
git config core.hooksPath .githooks
```

La compuerta recomendada antes de cada push es:

```powershell
.\scripts\pipa_preflight.ps1 -SkipStartupCheck
```

Esa ejecución es inerte: no abre aplicaciones, no envía mensajes, no contacta
con League y no modifica claves o configuración. Comprueba, entre otras cosas:

- pruebas del backend y Windows Agent;
- Ruff, Bandit, formato y compilación Python;
- sintaxis de todos los scripts PowerShell versionados;
- documentación y enlaces locales;
- políticas de logs, configuración y flashing;
- contratos Python, C++, Swift y TCP móvil;
- archivos publicables, patrones de secretos y todo el historial Git.

Para añadir las cinco compilaciones de firmware y el smoke test nativo, usa:

```powershell
.\scripts\pipa_preflight.ps1 `
  -SkipStartupCheck -CheckFirmware -CheckCredentialProvider
```

`-RequireHardware` convierte la ausencia de `PIPA_SERIAL_PORT` en un fallo. No
lo uses hasta conectar y reconocer físicamente la placa. El workflow de CI está
configurado para repetir las comprobaciones en Windows, Linux y macOS, fijar
las GitHub Actions externas por SHA, auditar las dependencias Python y construir
el firmware, Swift y el Credential Provider.

## Firmware y hardware

La configuración versionada contiene solo valores seguros vacíos. Copia
`firmware/include/pipa_device_config.example.h` a
`pipa_device_config.local.h`; el archivo local está ignorado por Git.

Antes de escribir en una placa, sigue
[firmware/ARRIVAL_CHECKLIST.md](firmware/ARRIVAL_CHECKLIST.md). El script de
flashing exige una revisión V1/V2 explícita, una opción de firmware de
desarrollo y confirmación antes de escribir. La imagen actual no tiene Secure
Boot, cifrado de Flash ni anti-rollback validados, por lo que no es firmware de
producción.

## Estructura del repositorio

```text
Pipa/
├── backend/          núcleo, protocolo, sesiones y simulador
├── firmware/         PlatformIO, drivers, vectores y pruebas host
├── mobile-ios/       paquete Swift, UI y proyecto Xcode
├── scripts/          preflight, seguridad, contratos y publicación
├── trusted-unlock/   Credential Provider y broker experimentales
└── windows-agent/    API local, CLI, herramientas y gateways
```

## Documentación técnica

- [Windows Agent](windows-agent/README.md)
- [Backend y Core](backend/README.md)
- [Firmware](firmware/README.md)
- [Cliente iOS](mobile-ios/README.md)
- [Trusted Unlock](trusted-unlock/README.md)
- [Protocolo móvil](MOBILE_PROTOCOL.md)
- [Sesión segura v2](SECURE_SESSION_PROTOCOL.md)
- [Audio cifrado](SECURE_AUDIO_PROTOCOL.md)
- [Checklist de publicación](docs/PUBLICATION_CHECKLIST.md)
- [Cómo citar](CITATION.cff)

## Seguridad

Lee [SECURITY.md](SECURITY.md) antes de habilitar transporte móvil, provisionar
claves o instalar el Credential Provider. No publiques una vulnerabilidad con
tokens, rutas, fingerprints completos, logs sin revisar o datos personales;
usa el canal privado descrito allí.

Antes de publicar o hacer push:

```powershell
.\scripts\check_repo_hygiene.ps1
.\scripts\check_git_history.ps1
git status --short
```

Si un secreto real entró alguna vez en un commit, ignorarlo después no basta:
hay que revocarlo y limpiar el historial y el remoto de forma coordinada.

## Contribuir

Las contribuciones deben conservar los límites de seguridad y acompañar cada
cambio de comportamiento con pruebas. Consulta
[CONTRIBUTING.md](CONTRIBUTING.md) antes de abrir una pull request.

## Licencia

El código propio de Pipα se distribuye bajo la [licencia MIT](LICENSE), con
copyright de `villarrubi`. Puedes usarlo, modificarlo y redistribuirlo siempre
que conserves el aviso de copyright y la licencia. Para dar crédito al autor,
consulta también [CITATION.cff](CITATION.cff). Las dependencias y archivos de
terceros conservan sus propias licencias y avisos en
[firmware/THIRD_PARTY_NOTICES.md](firmware/THIRD_PARTY_NOTICES.md).
