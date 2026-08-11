# Pipα — Personal AI Assistant

Pipα es un proyecto de asistente personal para Windows que combina un agente
local, automatización del PC, hardware ESP32/Waveshare y un futuro Trusted
Unlock controlado criptográficamente.

## Estado actual

- El Windows Agent puede consultar el sistema, controlar audio, abrir apps y
  bloquear el equipo.
- También puede abrir búsquedas web, búsquedas de Apple Music y aplicaciones
  configuradas como League o Codex, sin automatizar sus interfaces.
- El Credential Provider aparece como opción adicional en LogonUI.
- La tile de Pipα no autentica ni desbloquea Windows.
- El protocolo Ed25519 de desafío/respuesta tiene pruebas unitarias.
- Existe almacenamiento administrativo de claves públicas y tickets de una
  sola operación en memoria.
- Existe un broker local experimental con Named Pipe y ACL explícita, pero no
  tiene capacidad de desbloqueo.
- Todavía no existe un flujo de desbloqueo real ni integración con Waveshare.

La contraseña, el PIN, Windows Hello y los Credential Providers normales no se
sustituyen ni se desactivan.

## Estructura

```text
Pipa/
├── trusted-unlock/       Credential Provider x64 y scripts de instalación
├── windows-agent/        Agente local y núcleo de autorización
├── backend/              Espacio reservado para el backend futuro
└── firmware/             Espacio reservado para ESP32/Waveshare
```

## Requisitos

- Windows 11 x64.
- Python 3.12+.
- Visual Studio Community con herramientas C++ x64.
- Windows SDK.

Instala las dependencias del agente en un entorno virtual local:

```powershell
cd windows-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Ejecutar el agente

El agente escucha solo en `127.0.0.1:8765`:

```powershell
cd windows-agent
python main.py
```

No se debe exponer este servidor a la red ni añadirle un endpoint de
desbloqueo. Trusted Unlock usa un broker separado y un Named Pipe propio.

## Compilar y probar el Credential Provider

Desde **x64 Native Tools Command Prompt for VS 2026**:

```text
cd trusted-unlock\build
cmake --build . --config Release
.\Release\PipaProviderTest.exe
dumpbin /exports .\Release\PipaTrustedUnlock.dll
```

El smoke test debe terminar con `SMOKE TEST COMPLETADO`, mostrar `AutoLogon:
FALSE` y confirmar que no se entrega ninguna serialización.

## Pruebas Python

Desde la raíz del repositorio:

```powershell
python -B -m unittest discover -s windows-agent/tests -p "test_*.py"
```

Comprueba que el índice de Git no contiene builds, configuraciones locales ni
patrones sensibles:

```powershell
.\scripts\check_repo_hygiene.ps1
```

## Configuración local de aplicaciones

La configuración publicable es [apps.example.json](windows-agent/config/apps.example.json).
Para personalizar rutas o comandos, copia esa plantilla como
`windows-agent/config/apps.json`. Ese archivo está excluido por `.gitignore` y
no debe subirse al repositorio.

## Seguridad y recuperación

Antes de registrar el Credential Provider se debe haber probado el smoke test.
La instalación real usa:

```powershell
cd trusted-unlock
.\install.ps1 -WhatIf
```

Para retirar la integración:

```powershell
.\uninstall.ps1 -WhatIf
.\uninstall.ps1
```

El diseño completo y sus límites están en
[TRUSTED_UNLOCK_PROTOCOL.md](trusted-unlock/TRUSTED_UNLOCK_PROTOCOL.md).

## Higiene del repositorio

No se deben subir builds, DLL, EXE, PDB, objetos, logs, entornos virtuales,
`__pycache__`, claves privadas, certificados, tokens, archivos `.env`, dumps ni
configuraciones con rutas del ordenador.

El `.gitignore` evita nuevas inclusiones, pero no borra archivos que ya estén
en la historia de Git. Si el repositorio remoto ya contiene datos que deban
retirarse de su historial, primero hay que hacer una limpieza histórica
revisada y después un push coordinado.

El agente puede arrancarse automáticamente sin una ventana visible usando
`windows-agent/start_agent_hidden.ps1` y `windows-agent/install_agent_task.ps1`.
El archivo `start_agent.bat` queda reservado para ejecución manual y
depuración.

## Roadmap

1. Endurecer instalación, desinstalación y recuperación.
2. Ejecutar el broker como proceso controlado y probar reinicios, ACL y reloj.
3. Probar el broker con un dispositivo simulado y fallos adversarios.
4. Integrar el Credential Provider sin activar todavía la serialización.
5. Emparejar el futuro Waveshare mediante una clave privada que nunca salga
   del dispositivo.
6. Diseñar y probar la serialización de Windows como último paso.
