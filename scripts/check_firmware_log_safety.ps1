[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeFiles = @(
    (Join-Path $repoRoot 'firmware/src/main.cpp'),
    (Join-Path $repoRoot 'firmware/src/pipa_protocol.cpp'),
    (Join-Path $repoRoot 'firmware/src/pipa_secure_protocol.cpp')
)

foreach ($path in $runtimeFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta un runtime del firmware para la auditoria de logs: $path"
    }

    $source = Get-Content -LiteralPath $path -Raw
    foreach ($pattern in @(
            '(?m)\blog\(\s*(?:String\([^)]*\)\s*\+\s*)?WiFi\.localIP',
            '(?m)\blog\(\s*String\([^)]*\)\s*\+\s*WiFi\.localMACAddress',
            '(?m)\blog\(\s*String\([^)]*\)\s*\+\s*PIPA_WIFI_PASSWORD',
            '(?m)\blog\(\s*String\([^)]*\)\s*\+\s*PIPA_PC_MAC'
        )) {
        if ($source -match $pattern) {
            throw "El firmware no puede escribir datos de red o credenciales en logs: $path"
        }
    }
    if ($source -match '(?m)\blog\(String\("(?:server error|secure session reset)') {
        throw "El firmware no puede interpolar errores externos en logs: $path"
    }
}

Write-Host 'Seguridad de logs del firmware OK: no se registran IPs, credenciales ni errores dinamicos.' -ForegroundColor Green
Exit 0
