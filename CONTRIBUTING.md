# Contribuir a Pipα

Gracias por ayudar a mejorar Pipα. El proyecto controla software de escritorio,
red local, firmware y una superficie experimental de autenticación; los cambios
deben mantener un comportamiento conservador y verificable.

## Antes de empezar

- Lee [README.md](README.md) y [SECURITY.md](SECURITY.md).
- Para una vulnerabilidad, no abras una issue pública. Usa el canal privado
  indicado en la sección "Reportar una vulnerabilidad" de `SECURITY.md`.
- No incluyas rutas personales, teléfonos, IDs, MAC, SSID, claves, tokens,
  capturas, logs sin revisar ni configuración local.
- Las propuestas de desbloqueo real, envío automático, llamadas automáticas o
  exposición de listeners necesitan primero un modelo de amenaza explícito.

## Preparar el entorno

En Windows con Python 3.12:

```powershell
.\windows-agent\setup_agent.ps1 -SkipTask
.\windows-agent\.venv\Scripts\python.exe -m pip install `
  -r .\windows-agent\requirements-dev.txt
git config core.hooksPath .githooks
```

La configuración personal debe vivir únicamente en las rutas ignoradas que
documenta el README de cada componente. Usa los archivos `*.example.*` como
punto de partida.

## Criterios para una pull request

1. Mantén el cambio pequeño y explica el riesgo o comportamiento que modifica.
2. Añade pruebas para rutas correctas, entradas inválidas y fallo seguro.
3. No amplíes allowlists, destinos de red ni permisos de forma implícita.
4. Actualiza el documento de protocolo o el README del componente si cambia un
   contrato público.
5. Ejecuta el preflight y deja claros los chequeos dependientes de hardware que
   no hayas podido realizar.

```powershell
.\scripts\pipa_preflight.ps1 -SkipStartupCheck
git diff --check
git status --short
```

Si tienes el toolchain correspondiente, añade `-CheckFirmware` y
`-CheckCredentialProvider`. Swift y el proyecto iOS se validan en macOS mediante
la CI.

## Convenciones

- Python: 3.12, Ruff y líneas de hasta 110 caracteres.
- PowerShell: compatible con Windows PowerShell 5.1; evita secretos en salida y
  mensajes de excepción sin filtrar.
- Protocolos: esquemas estrictos, tamaños acotados, campos extra rechazados y
  resultados minimizados.
- GitHub Actions externas: siempre fijadas a un SHA completo de 40 caracteres.
- Commits: mensajes descriptivos y sin artefactos generados.

## Licencia de contribuciones

El código propio del proyecto se distribuye bajo la licencia MIT de
[LICENSE](LICENSE). Las contribuciones deben ser originales o tener una licencia
compatible, y deben conservar los avisos de terceros cuando corresponda. La
licencia no transfiere el copyright de una contribución: cada autor conserva
sus derechos sobre el código que aporta.
