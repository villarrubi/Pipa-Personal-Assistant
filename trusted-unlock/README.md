Pipα Trusted Unlock
===================

Este directorio contiene un Credential Provider x64 experimental para Windows.

Estado actual
-------------

La DLL implementa la tile adicional `Pipα Trusted Unlock`, pero todavía no
autentica ni entrega credenciales a Windows. `GetSerialization` devuelve
`CPGSR_NO_CREDENTIAL_NOT_FINISHED` y el autologon está desactivado.

Compilar y probar
-----------------

Usa una consola **x64 Native Tools Command Prompt for VS 2026**:

```text
cd trusted-unlock\build
cmake --build . --config Release
.\Release\PipaProviderTest.exe
dumpbin /exports .\Release\PipaTrustedUnlock.dll
```

Instalación controlada
----------------------

La instalación real requiere PowerShell como administrador y se debe hacer
solo después de confirmar que el smoke test pasa:

```powershell
cd trusted-unlock
.\install.ps1 -WhatIf
.\install.ps1
```

El instalador muestra el SHA-256 de la DLL. En una distribución revisada se
puede exigir una huella concreta:

```powershell
.\install.ps1 -ExpectedSha256 <64_HEX>
```

El script copia la DLL a `C:\Program Files\Pipa\TrustedUnlock` y crea
únicamente estas entradas x64:

```text
HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{7D886843-37F4-4C64-A45A-8550F112E57A}
HKLM\SOFTWARE\Classes\CLSID\{7D886843-37F4-4C64-A45A-8550F112E57A}\InprocServer32
```

No se usa `regsvr32`: esta DLL exporta `DllGetClassObject`, pero no contiene
un instalador COM automático. El script rechaza claves existentes para no
sobrescribir instalaciones ajenas.

Rollback
--------

Para retirar Pipα:

```powershell
.\uninstall.ps1 -WhatIf
.\uninstall.ps1
```

El rollback elimina solo las claves asociadas al CLSID de Pipα y la DLL bajo
`%ProgramFiles%\Pipa\TrustedUnlock`. No modifica contraseña, PIN, Windows
Hello, políticas de inicio de sesión ni otros Credential Providers.
