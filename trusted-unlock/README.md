Pipα Trusted Unlock
===================

Este directorio contiene un Credential Provider x64 experimental para Windows.

Estado actual
-------------

La DLL implementa la tile adicional `Pipα Trusted Unlock`, pero todavía no
autentica ni entrega credenciales a Windows. La tile se muestra como
`Desactivado: no autentica`, `GetSerialization` devuelve
`CPGSR_NO_CREDENTIAL_NOT_FINISHED`, el proveedor rechaza serializaciones
externas y el autologon está desactivado.

Compilar y probar
-----------------

Usa una consola **x64 Native Tools Command Prompt for VS 2026**:

```text
cmake -S trusted-unlock -B trusted-unlock\build -A x64
cmake --build trusted-unlock\build --config Release
.\trusted-unlock\build\Release\PipaProviderTest.exe
dumpbin /exports .\trusted-unlock\build\Release\PipaTrustedUnlock.dll
```

El smoke test debe terminar con `SMOKE TEST COMPLETADO`, mantener autologon en
`FALSE` y confirmar que no se entrega ninguna serialización. La CI repite una
build x64 limpia en `build-ci`; los binarios nunca deben entrar en Git.

Si la build local ya existe, el preflight puede repetir ese smoke test sin
registrar la DLL ni tocar el Registro:

```powershell
.\scripts\pipa_preflight.ps1 -CheckCredentialProvider -SkipStartupCheck
```

Instalación controlada
----------------------

Antes de registrar una clave, calcula su fingerprint sin modificar el Registro
y compáralo con el valor obtenido por un canal físico:

```powershell
.\windows-agent\.venv\Scripts\python.exe .\windows-agent\trusted_unlock_admin.py fingerprint `
  --public-key <CLAVE_PUBLICA_BASE64URL>
```

El comando `pair` debe ejecutarse solo después de esa comprobación y exige
repetirla con `--expected-fingerprint`; una discrepancia no modifica el
Registro.

La instalación real requiere PowerShell como administrador y se debe hacer
solo después de confirmar que el smoke test pasa:

```powershell
cd trusted-unlock
.\install.ps1 -WhatIf
.\install.ps1
```

El instalador muestra el SHA-256 de la DLL. Rechaza DLL, carpeta de instalación
o carpeta padre que sean enlaces/reparse points, y vuelve a calcular el hash
después de copiar para detectar cambios entre la comprobación y la instalación.
En una distribución revisada se puede exigir una huella concreta:

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
sobrescribir instalaciones ajenas. La copia y el registro forman una
operación transaccional: si se rechaza cualquiera de las dos confirmaciones,
el instalador revierte la copia y no deja una instalación parcial. Con
`-WhatIf` no se escribe nada.

Rollback
--------

Para retirar Pipα:

```powershell
.\uninstall.ps1 -WhatIf
.\uninstall.ps1
```

El rollback comprueba también que las rutas no sean enlaces/reparse points y
elimina solo las claves asociadas al CLSID de Pipα y la DLL bajo
`%ProgramFiles%\Pipa\TrustedUnlock`. No modifica contraseña, PIN, Windows
Hello, políticas de inicio de sesión ni otros Credential Providers.
Antes de borrar, comprueba también que las claves contienen exactamente los
valores y la subclave creados por el instalador; si alguien las ha modificado,
se detiene sin borrar nada.
