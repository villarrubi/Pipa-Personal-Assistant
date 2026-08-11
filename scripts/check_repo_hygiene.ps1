[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$trackedFiles = @(git -C $repoRoot ls-files)
$violations = [System.Collections.Generic.List[string]]::new()

$forbiddenPathPattern = '(^|/)(build|__pycache__|\.venv|venv|out|bin)(/|$)|(^|/)windows-agent/config/apps\.json$'
foreach ($path in $trackedFiles) {
    if ($path -match $forbiddenPathPattern) {
        $violations.Add("Archivo generado o local rastreado: $path")
    }
}

$windowsUserPath = 'C:' + '\\Users\\'
$portableUserPath = 'C:' + '/Users/'
$sensitiveContentPattern = (
    [regex]::Escape($windowsUserPath) + '|' +
    [regex]::Escape($portableUserPath) + '|' +
    'BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|' +
    '(password|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*"'
)
$matches = @(git -C $repoRoot grep -n -I -i -E $sensitiveContentPattern -- ':!*.pyc' 2>$null)
if ($LASTEXITCODE -eq 0) {
    foreach ($match in $matches) {
        $violations.Add("Contenido potencialmente sensible: $match")
    }
}

if ($violations.Count -gt 0) {
    $violations | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Higiene Git OK: $($trackedFiles.Count) archivos rastreados revisados." -ForegroundColor Green
