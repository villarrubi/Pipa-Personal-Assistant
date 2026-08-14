[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$protocolSources = @(
    (Join-Path $repoRoot 'firmware/src/pipa_protocol.cpp'),
    (Join-Path $repoRoot 'firmware/src/pipa_secure_protocol.cpp')
)

foreach ($sourcePath in $protocolSources) {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Falta el protocolo de recuperación de UI: $sourcePath"
    }

    $source = Get-Content -LiteralPath $sourcePath -Raw
    foreach ($marker in @(
            'strcmp(type, "error") == 0',
            'La solicitud no ha podido completarse.',
            'confirmation_id.clear()',
            'confirmation_summary.clear()'
        )) {
        if ($source.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
            throw "El protocolo no invalida la UI pendiente tras un error: $marker ($sourcePath)"
        }
    }
}

Write-Host 'Recuperación de UI firmware OK: los errores limpian confirmaciones obsoletas y el estado de pensamiento.' -ForegroundColor Green
Exit 0
