[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$reviewedFiles = @(git -C $repoRoot ls-files --cached --others --exclude-standard)
$violations = [System.Collections.Generic.List[string]]::new()

$forbiddenPathPattern = (
    '(^|/)(build|build-ci|__pycache__|\.venv|venv|out|bin|obj|dist|\.pio|\.platformio)(/|$)|' +
    '(^|/)windows-agent/config/apps\.json$|' +
    '(^|/)firmware/include/pipa_device_config\.local\.h$'
)
foreach ($path in $reviewedFiles) {
    if ($path -match $forbiddenPathPattern) {
        $violations.Add("Archivo generado o local rastreado: $path")
    }
    $absolutePath = Join-Path $repoRoot $path
    if ((Test-Path -LiteralPath $absolutePath -PathType Leaf) -and
        (Get-Item -LiteralPath $absolutePath).Length -gt 5MB) {
        $violations.Add("Archivo rastreado mayor de 5 MiB: $path")
    }
}

$windowsUserPath = 'C:' + '\\Users\\'
$portableUserPath = 'C:' + '/Users/'
$sensitiveContentPattern = (
    [regex]::Escape($windowsUserPath) + '|' +
    [regex]::Escape($portableUserPath) + '|' +
    'BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|' +
    'gh[oprsu]_[A-Za-z0-9]{20,}|' +
    'sk-(proj-)?[A-Za-z0-9_-]{20,}|' +
    'AKIA[0-9A-Z]{16}|' +
    '(password|secret|api[_-]?key|token)\s*[:=]\s*"'
)
foreach ($path in $reviewedFiles) {
    $absolutePath = Join-Path $repoRoot $path
    if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
        (Get-Item -LiteralPath $absolutePath).Length -gt 5MB) {
        continue
    }
    $matches = @(Select-String -LiteralPath $absolutePath -Pattern $sensitiveContentPattern)
    foreach ($match in $matches) {
        $violations.Add("Contenido potencialmente sensible: ${path}:$($match.LineNumber)")
    }
}

$safeDeviceConfig = Join-Path $repoRoot 'firmware/include/pipa_device_config.h'
if (Test-Path -LiteralPath $safeDeviceConfig -PathType Leaf) {
    $configText = Get-Content -LiteralPath $safeDeviceConfig -Raw
    if ($configText -notmatch '#define PIPA_WIFI_SSID ""' -or
        $configText -notmatch '#define PIPA_WIFI_PASSWORD ""' -or
        $configText -notmatch '#define PIPA_PC_MAC "00:00:00:00:00:00"') {
        $violations.Add('La configuración de firmware rastreada no contiene valores locales seguros.')
    }
}

if ($violations.Count -gt 0) {
    $violations | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Higiene Git OK: $($reviewedFiles.Count) archivos publicables revisados." -ForegroundColor Green
