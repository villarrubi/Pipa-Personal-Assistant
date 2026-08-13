[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$violations = [System.Collections.Generic.List[string]]::new()
$revisions = @(git -C $repoRoot rev-list --all)

$forbiddenPathPattern = (
    '(^|/)(build|build-ci|\.venv|venv|out|bin|obj|dist|\.pio|\.platformio)(/|$)|' +
    '(^|/)windows-agent/config/apps\.json$|' +
    '(^|/)firmware/include/pipa_device_config\.local\.h$|' +
    '\.(dll|exe|pdb|dmp|pem|key|pfx|p12)$'
)
$historicalPaths = @(
    git -C $repoRoot log --all --format= --name-only |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique
)
foreach ($path in $historicalPaths) {
    if ($path -match $forbiddenPathPattern) {
        $violations.Add("Ruta local o generada presente en el historial: $path")
    }
}

$windowsUserPath = 'C:' + '\Users\'
$portableUserPath = 'C:' + '/Users/'
$highConfidencePattern = (
    [regex]::Escape($windowsUserPath) + '|' +
    [regex]::Escape($portableUserPath) + '|' +
    'BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY|' +
    'gh[oprsu]_[A-Za-z0-9]{20,}|' +
    'sk-(proj-)?[A-Za-z0-9_-]{20,}|' +
    'AKIA[0-9A-Z]{16}|' +
    'glpat-[A-Za-z0-9_-]{20,}|' +
    'xox[baprs]-[A-Za-z0-9-]{10,}|' +
    'npm_[A-Za-z0-9]{30,}|' +
    'AIza[0-9A-Za-z_-]{30,}|' +
    'mfa\.[A-Za-z0-9_-]{20,}|' +
    '(sk|rk)_live_[A-Za-z0-9]{16,}|' +
    '[0-9]{8,12}:[A-Za-z0-9_-]{35}'
)
foreach ($revision in $revisions) {
    $matches = @(
        git -C $repoRoot grep -I -l -E $highConfidencePattern $revision -- . 2>$null
    )
    foreach ($match in $matches) {
        $violations.Add("Contenido sensible probable en el historial: $match")
    }
}

if ($violations.Count -gt 0) {
    $violations | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Historial Git OK: $($revisions.Count) revisiones comprobadas." -ForegroundColor Green
exit 0
