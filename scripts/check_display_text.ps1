[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$headerPath = Join-Path $repoRoot 'firmware/src/pipa_display_text.h'
$sourcePath = Join-Path $repoRoot 'firmware/src/pipa_display_text.cpp'
$testPath = Join-Path $repoRoot 'firmware/tests/pipa_display_text_host_test.cpp'
$displayPath = Join-Path $repoRoot 'firmware/src/pipa_display.cpp'

foreach ($path in @($headerPath, $sourcePath, $testPath, $displayPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta un artefacto de texto de pantalla: $path"
    }
}

$header = Get-Content -LiteralPath $headerPath -Raw
$source = Get-Content -LiteralPath $sourcePath -Raw
$display = Get-Content -LiteralPath $displayPath -Raw
$test = Get-Content -LiteralPath $testPath -Raw

foreach ($required in @('normalizeSummary', 'splitSummary', 'kMaxSummaryBytes', 'kMaxLineCharacters')) {
    if ($header.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0 -and
        $source.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0) {
        throw "Falta el contrato de texto de pantalla: $required"
    }
}
if ($source -match '(?i)#include\s*[<"](?:Arduino|Wire|WiFi|esp_lcd|driver/)') {
    throw 'El módulo host de texto de pantalla no puede depender de hardware.'
}
if ($display.IndexOf('pipa_display_text.h', [System.StringComparison]::Ordinal) -lt 0 -or
    $display.IndexOf('display_text::normalizeSummary', [System.StringComparison]::Ordinal) -lt 0 -or
    $display.IndexOf('display_text::splitSummary', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El driver de pantalla no usa el módulo de texto aislado.'
}
if ($test.IndexOf('normalizeSummary', [System.StringComparison]::Ordinal) -lt 0 -or
    $test.IndexOf('splitSummary', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'Falta la prueba host del texto de pantalla.'
}

Write-Host 'Compuerta de texto de pantalla: módulo aislado y prueba host presentes.' -ForegroundColor Green
