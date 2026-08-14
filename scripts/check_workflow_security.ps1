[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workflowDirectory = Join-Path $repoRoot '.github/workflows'
if (-not (Test-Path -LiteralPath $workflowDirectory -PathType Container)) {
    throw 'No se encuentra el directorio de workflows.'
}

$workflowFiles = @(
    Get-ChildItem -LiteralPath $workflowDirectory -File -Recurse |
        Where-Object { $_.Extension -in @('.yml', '.yaml') }
)
if ($workflowFiles.Count -eq 0) {
    throw 'No se encontraron workflows para auditar.'
}

$violations = [System.Collections.Generic.List[string]]::new()
$externalReferences = 0

foreach ($file in $workflowFiles) {
    $lineNumber = 0
    foreach ($line in Get-Content -LiteralPath $file.FullName) {
        $lineNumber++
        if ($line -notmatch '^\s*-\s*uses:\s*(?<reference>[^\s#]+)') {
            continue
        }

        $reference = $Matches.reference
        if ($reference.StartsWith('./', [System.StringComparison]::Ordinal) -or
            $reference.StartsWith('../', [System.StringComparison]::Ordinal)) {
            continue
        }

        $externalReferences++
        $at = $reference.LastIndexOf('@')
        if ($at -le 0 -or $at -eq ($reference.Length - 1)) {
            $violations.Add("Referencia de action sin revision inmutable: $($file.Name):$lineNumber")
            continue
        }

        $revision = $reference.Substring($at + 1)
        if ($revision -notmatch '^[0-9a-fA-F]{40}$') {
            $violations.Add("Action externa no fijada a SHA: $($file.Name):$lineNumber")
        }
    }
}

if ($externalReferences -eq 0) {
    throw 'No se encontraron referencias externas de actions para auditar.'
}
if ($violations.Count -gt 0) {
    $violations | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host ("Seguridad de workflows OK: {0} referencias externas fijadas por SHA." -f $externalReferences) -ForegroundColor Green
exit 0
