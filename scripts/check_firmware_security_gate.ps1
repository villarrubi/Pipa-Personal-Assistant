[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$checker = Join-Path $repoRoot 'windows-agent/firmware_security_check.py'
$flasher = Join-Path $repoRoot 'scripts/flash_waveshare.ps1'
foreach ($path in @($checker, $flasher)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta el componente de la barrera eFuse: $path"
    }
}

$checkerContent = Get-Content -LiteralPath $checker -Raw
$flasherContent = Get-Content -LiteralPath $flasher -Raw
foreach ($marker in @(
        'SPI_BOOT_CRYPT_CNT',
        'SECURE_BOOT_EN',
        'SECURE_VERSION',
        'read_only',
        'never invokes a burn command'
    )) {
    if ($checkerContent.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "La sonda eFuse no contiene el control requerido: $marker"
    }
}
foreach ($marker in @(
        'firmware_security_check.py',
        'securityReport.success -ne $true',
        'no se ha flasheado nada'
    )) {
    if ($flasherContent.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El cargador no aplica la barrera eFuse: $marker"
    }
}

Write-Host 'Barrera eFuse OK: el flasheo de desarrollo requiere una lectura segura del estado del chip.' -ForegroundColor Green
