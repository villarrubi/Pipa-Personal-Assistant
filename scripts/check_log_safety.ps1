[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeFiles = @(
    (Join-Path $repoRoot 'windows-agent/main.py'),
    (Join-Path $repoRoot 'windows-agent/pipa_serial_gateway.py'),
    (Join-Path $repoRoot 'windows-agent/secure_serial_gateway.py'),
    (Join-Path $repoRoot 'windows-agent/secure_tcp_gateway.py')
)

foreach ($path in $runtimeFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta un runtime del agente para la auditoria de logs: $path"
    }

    $source = Get-Content -LiteralPath $path -Raw
    if ($source -match '(?m)\bLOGGER\.exception\s*\(') {
        throw "No se permite LOGGER.exception en el runtime del agente: $path"
    }
    if ($source -match '(?m)\bLOGGER\.(?:error|warning|info)\([^\r\n]*(?:,\s*error|,\s*self\.port|,\s*port)\s*\)') {
        throw "El runtime no puede escribir excepciones o puertos dinamicos en el log: $path"
    }
}

Write-Host 'Seguridad de logs OK: el runtime no registra excepciones ni rutas/puertos dinamicos.' -ForegroundColor Green
Exit 0
