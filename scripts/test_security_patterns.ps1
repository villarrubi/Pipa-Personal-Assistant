[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$patternsPath = Join-Path $PSScriptRoot 'security_patterns.ps1'
if (-not (Test-Path -LiteralPath $patternsPath -PathType Leaf)) {
    throw "Falta la fuente comun de patrones de seguridad: $patternsPath"
}
. $patternsPath

$highConfidencePattern = Get-PipaHighConfidenceSecretPattern
$workingTreePattern = Get-PipaWorkingTreeSecretPattern
$syntheticTokens = @(
    ('ghp_' + ('A' * 24)),
    ('glpat-' + ('B' * 24)),
    ('xoxb-' + ('C' * 16)),
    ('npm_' + ('D' * 32)),
    ('AIza' + ('E' * 32)),
    ('mfa.' + ('F' * 24)),
    ('sk_live_' + ('G' * 20)),
    ('123456789:' + ('H' * 35))
)

foreach ($token in $syntheticTokens) {
    if ($token -notmatch $highConfidencePattern) {
        throw 'El patron comun no detecta uno de sus formatos sinteticos.'
    }
}

$normalText = 'texto de diagnostico sin credenciales ni secretos'
if ($normalText -match $highConfidencePattern -or $normalText -match $workingTreePattern) {
    throw 'Los patrones de seguridad marcan texto normal como secreto.'
}

$genericSecret = ('password' + ': "' + 'valor local')
if ($genericSecret -notmatch $workingTreePattern) {
    throw 'La politica del arbol no detecta una asignacion generica de secreto.'
}

Write-Host 'Patrones de seguridad OK: formatos sinteticos detectados sin falsos positivos.' -ForegroundColor Green
