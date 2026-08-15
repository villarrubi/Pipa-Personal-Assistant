# Pipα — asistente personal local para Windows

Pipα es un asistente personal local que permite controlar el ordenador con
instrucciones de voz y procesos configurables. Combina un agente para Windows,
un núcleo de comandos confirmables, una interfaz física basada en Waveshare
ESP32-S3 y un cliente iOS experimental.

La idea es sencilla: poder decirle a Pipa qué hacer, mantener el control sobre
cada acción y añadir nuevas capacidades sin convertir el sistema en una caja
negra.

## Qué puedes hacer

- Crear y editar archivos y abrir VS Code para programar por voz.
- Abrir aplicaciones configuradas desde el ordenador o desde el panel local.
- Buscar en Internet y abrir contenidos en el navegador.
- Preparar mensajes de WhatsApp y, si se configura explícitamente, enviarlos
  mediante WhatsApp Cloud API.
- Abrir Discord y destinos configurados sin iniciar llamadas automáticamente.
- Consultar y controlar acciones de League of Legends con confirmación manual.
- Ajustar volumen, controlar reproducción multimedia y crear temporizadores.
- Añadir procesos nuevos y editar las frases que Pipa entiende desde el panel.

Las acciones externas requieren confirmación. WhatsApp funciona en modo manual
por defecto; Pipa no automatiza el teclado, no acepta partidas de League, no
selecciona pistas ni realiza envíos sin la autorización correspondiente.

## Panel de control

Con el agente local en ejecución, abre:

<http://127.0.0.1:8765/panel>

Desde ahí puedes:

- Activar o desactivar procesos y comandos.
- Editar frases y parámetros del catálogo.
- Añadir nuevos procesos con una lista de ejecución validada.
- Ejecutar aplicaciones configuradas con confirmación explícita.
- Configurar el modo manual o automático de WhatsApp.
- Consultar el estado del agente y de sus integraciones.

El panel solo está disponible en el propio ordenador: el agente HTTP/WebSocket
escucha únicamente en 127.0.0.1.

## Hardware

La interfaz física está basada en el Waveshare ESP32-S3-Touch-LCD-1.85C-BOX
(SKU 30684). El dispositivo está preparado para aportar pantalla táctil,
audio, identidad criptográfica y comunicación USB CDC con el ordenador.

El firmware compila para las revisiones V1 y V2. La validación física de la
pantalla, el touch y el audio depende de disponer de la placa y sigue separada
del flujo de pruebas del software.

## Arquitectura

~~~text
Waveshare ESP32-S3 ── USB CDC + identidad Ed25519 ──┐
                                                     ├─> Pipα Core ──> Windows
iPhone ───────── TCP v2 cifrado y opt-in ───────────┘       │
                                                            ├─> herramientas
                                                            └─> confirmaciones

Credential Provider experimental ──> broker local ──> desbloqueo desactivado
~~~

El núcleo separa transporte, estado, confirmaciones y herramientas. El
transporte móvil está desactivado por defecto y solo se habilita con una
configuración local explícita.

## Estado del proyecto

| Componente | Estado |
| --- | --- |
| Windows Agent | Funcional en 127.0.0.1:8765, con CLI, panel y logs locales |
| Pipα Core | Sesiones, herramientas, confirmaciones y resultados redactados |
| Integraciones | Aplicaciones, navegador, multimedia, temporizadores, League, WhatsApp y Discord |
| Panel de control | Procesos, comandos y automatizaciones editables |
| Gateway Waveshare | Implementado por USB CDC; requiere puerto COM y hardware real |
| Firmware | Builds V1/V2 y pruebas host; falta validación física completa |
| Cliente iOS | Core, SwiftUI, CryptoKit/Keychain y TCP v2; pendiente de probar en iPhone real |
| Trusted Unlock | Experimental, desactivado y no sustitutivo de Windows Hello |

El software local se puede probar sin la placa. El firmware, el transporte
móvil y Trusted Unlock no se consideran componentes de producción hasta completar
su validación específica.

## Inicio rápido sin hardware

Requisitos del flujo principal:

- Windows 10/11.
- Python 3.12.
- PowerShell 5.1 o PowerShell 7.
- Git.

Desde PowerShell, en la raíz del repositorio:

~~~powershell
# Crea el entorno e instala las dependencias del agente sin registrar una tarea.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\windows-agent\setup_agent.ps1 -SkipTask

# Ejecuta un diagnóstico local inerte.
.\windows-agent\.venv\Scripts\python.exe .\windows-agent\pipa_cli.py local-self-test

# Inicia el agente oculto y consulta su estado.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\windows-agent\start_agent_hidden.ps1
.\windows-agent\.venv\Scripts\python.exe .\windows-agent\pipa_cli.py doctor
~~~

Para instalar el inicio automático por usuario:

~~~powershell
.\windows-agent\install_agent_task.ps1
~~~

La tarea se registra con privilegios limitados y no necesita elevación.

## Uso seguro desde la CLI

~~~powershell
# Estado y diagnóstico
python .\windows-agent\pipa_cli.py doctor
python .\windows-agent\pipa_cli.py readiness

# Interpretar o previsualizar sin ejecutar
python .\windows-agent\pipa_cli.py intent "abre WhatsApp para mama"
python .\windows-agent\pipa_cli.py preview "busca una partida de LoL"

# Pruebas inertes de protocolo y cifrado
python .\windows-agent\pipa_cli.py secure-test
python .\windows-agent\pipa_cli.py mobile-tcp-test
python .\windows-agent\pipa_cli.py integration-protocol-test
~~~

Las acciones externas lanzadas desde la CLI exigen --confirm. Las rutas,
alias, teléfonos, identidades y credenciales locales se guardan en archivos
ignorados por Git. Los ejemplos seguros están en
windows-agent/config/*.example.json.

## Validación

La compuerta local recomendada antes de cada push es:

~~~powershell
.\scripts\pipa_preflight.ps1 -SkipStartupCheck
~~~

El preflight comprueba pruebas Python, Ruff, Bandit, compilación, sintaxis
PowerShell, contratos Python/C++/Swift, documentación, patrones de secretos,
políticas de configuración y archivos publicables. Las comprobaciones que
requieren hardware se activan por separado:

~~~powershell
.\scripts\pipa_preflight.ps1 -SkipStartupCheck -CheckFirmware -CheckCredentialProvider
~~~

## Estructura del repositorio

~~~text
Pipa/
├── backend/          núcleo, protocolo, sesiones y simulador
├── firmware/         PlatformIO, drivers, vectores y pruebas host
├── mobile-ios/       paquete Swift, UI y proyecto Xcode
├── scripts/          preflight, seguridad, contratos y publicación
├── trusted-unlock/   Credential Provider y broker experimentales
└── windows-agent/    API local, CLI, herramientas y gateways
~~~

## Documentación

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

Consulta [SECURITY.md](SECURITY.md) antes de habilitar el transporte móvil,
provisionar claves o instalar el Credential Provider. El modelo está diseñado
para fallar cerrado, pedir confirmación en acciones externas y minimizar los
datos que llegan a la pantalla o a los dispositivos emparejados.

Pipα no protege frente a malware que ya se ejecute con la misma cuenta de
Windows. No publiques tokens, fingerprints completos, logs sin revisar ni datos
personales en issues o commits.

## Contribuir

Las contribuciones deben conservar los límites de seguridad y acompañar cada
cambio de comportamiento con pruebas. Consulta
[CONTRIBUTING.md](CONTRIBUTING.md) antes de abrir una pull request.

## Licencia

El código propio de Pipα se distribuye bajo la licencia MIT, con copyright de
villarrubi. Las dependencias y archivos de terceros conservan sus propias
licencias y avisos en
[firmware/THIRD_PARTY_NOTICES.md](firmware/THIRD_PARTY_NOTICES.md).
