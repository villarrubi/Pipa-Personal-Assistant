# Pipα Windows Agent

Agente local para automatización del PC. En su estado actual ofrece consulta
de estado, apertura de aplicaciones y URLs HTTP/HTTPS, bloqueo del equipo y
control del audio.

El servidor se enlaza a `127.0.0.1:8765`. No debe cambiarse a `0.0.0.0` ni
usarse como broker de Trusted Unlock. El agente vive en la sesión del usuario;
el futuro flujo de LogonUI necesitará un servicio separado y un IPC protegido.

## Configuración

`config/apps.example.json` es la configuración segura para compartir. Para
rutas específicas del ordenador, crea `config/apps.json`; ese archivo está
ignorado por Git.

## Administración de dispositivos

La CLI administrativa guarda solo claves públicas en el Registro x64 de
Windows y requiere una consola elevada para modificarlo:

```powershell
python .\trusted_unlock_admin.py list
python .\trusted_unlock_admin.py pair --device-id phone-main --public-key CLAVE_PUBLICA_BASE64URL
python .\trusted_unlock_admin.py revoke --device-id phone-main --yes
```

La clave privada debe permanecer en el móvil o hardware autorizado.

## Inicio sin ventana

Para el inicio automático, configura la tarea existente para ejecutar
`start_agent.vbs` mediante `wscript.exe`. Así el agente se inicia sin dejar
una ventana CMD visible. Ejecuta PowerShell como administrador (la tarea de
Windows requiere permisos para cambiar su acción):

```powershell
.\install_agent_task.ps1 -WhatIf
.\install_agent_task.ps1
```

`start_agent.bat` se mantiene como lanzador manual y de depuración; ese sí
abre una consola para poder ver los mensajes del agente.
