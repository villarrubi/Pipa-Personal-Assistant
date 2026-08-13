[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$flashScript = Join-Path $repoRoot 'scripts/flash_waveshare.ps1'
if (-not (Test-Path -LiteralPath $flashScript -PathType Leaf)) {
    throw 'Falta el script de flasheo del Waveshare.'
}

$content = Get-Content -LiteralPath $flashScript -Raw
foreach ($marker in @(
        '[switch]$AllowDevelopmentFirmware',
        'if (-not $AllowDevelopmentFirmware)',
        'no incluyen Secure Boot ni cifrado de Flash',
        'no es una imagen de produccion segura'
    )) {
    if ($content.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El script de flasheo no mantiene la barrera de firmware de desarrollo: $marker"
    }
}

Write-Host 'Barrera de flasheo segura: la imagen de desarrollo exige confirmacion explicita.' -ForegroundColor Green
