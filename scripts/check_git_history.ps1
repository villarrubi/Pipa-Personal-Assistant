[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$patternsPath = Join-Path $PSScriptRoot 'security_patterns.ps1'
if (-not (Test-Path -LiteralPath $patternsPath -PathType Leaf)) {
    throw "Falta la fuente común de patrones de seguridad: $patternsPath"
}
. $patternsPath

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
$highConfidencePattern = [regex]::Escape($windowsUserPath) + '|' +
    [regex]::Escape($portableUserPath) + '|' +
    (Get-PipaHighConfidenceSecretPattern)
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
