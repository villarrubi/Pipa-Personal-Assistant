[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $repoRoot 'windows-agent/secure_audio.py'
$pythonTestPath = Join-Path $repoRoot 'windows-agent/tests/test_secure_audio.py'
$swiftPath = Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaSecureAudio.swift'
$fixturePath = Join-Path $repoRoot 'mobile-ios/Tests/Fixtures/secure_audio_v2.json'

foreach ($path in @($pythonPath, $pythonTestPath, $swiftPath, $fixturePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta un artefacto del contrato de audio seguro: $path"
    }
}

$python = Get-Content -LiteralPath $pythonPath -Raw
$swift = Get-Content -LiteralPath $swiftPath -Raw
$fixture = Get-Content -LiteralPath $fixturePath -Raw

foreach ($required in @(
    'AUDIO_PROTOCOL_VERSION = 2',
    'AUDIO_AAD_PREFIX = b"pipa/audio/v2\x00"',
    'MAX_AUDIO_CHUNK_BYTES = 4096',
    'MAX_AUDIO_CHUNKS = 64',
    'MAX_AUDIO_STREAM_BYTES = MAX_AUDIO_CHUNK_BYTES * MAX_AUDIO_CHUNKS',
    'session.seal(samples, additional_data='
)) {
    if ($python.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El contrato Python no contiene el límite o la operación requerida: $required"
    }
}

foreach ($required in @(
    'protocolVersion = 2',
    'aadPrefix = Data("pipa/audio/v2\0".utf8)',
    'maxChunkBytes = 4_096',
    'maxChunks = 64',
    'sealBinary('
)) {
    if ($swift.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El contrato Swift no contiene el límite o la operación requerida: $required"
    }
}

if ($python -match '(?im)\bprint\s*\(' -or $python -match '(?i)\bSerial\b') {
    throw 'El módulo Python de audio no puede imprimir ni escribir en un puerto serie.'
}
if ($python -match '(?i)["'']samples["'']\s*:') {
    throw 'Las muestras no pueden aparecer como un campo JSON en el módulo Python.'
}
if ($swift -match '(?i)["'']samples["'']\s*:') {
    throw 'Las muestras no pueden aparecer como un campo JSON en el módulo Swift.'
}
if ($fixture -notmatch '"ciphertext"\s*:\s*"[^"\r\n]+"' -or
    $fixture -match '(?s)"frame"\s*:\s*\{[^}]*"samples"\s*:') {
    throw 'El vector debe contener ciphertext y no puede transportar samples dentro de la trama.'
}

$productionPython = @(Get-ChildItem -Path @(
    (Join-Path $repoRoot 'backend'),
    (Join-Path $repoRoot 'windows-agent')
) -Filter '*.py' -File -Recurse | Where-Object {
    $_.FullName -notmatch '\\tests\\' -and $_.FullName -ne $pythonPath
})
foreach ($path in $productionPython) {
    $source = Get-Content -LiteralPath $path.FullName -Raw
    if ($source -match '(?im)^\s*(?:from\s+secure_audio\s+import|import\s+secure_audio)\b') {
        throw "El audio seguro no puede conectarse aún al código residente: $($path.FullName)"
    }
}

$productionFirmware = @(Get-ChildItem -Path (Join-Path $repoRoot 'firmware/src') -Include '*.cpp', '*.h' -File -Recurse)
foreach ($path in $productionFirmware) {
    $source = Get-Content -LiteralPath $path.FullName -Raw
    if ($source -match '(?i)PipaSecureAudio|secure_audio') {
        throw "El audio seguro no puede conectarse aún al firmware: $($path.FullName)"
    }
}

Write-Host 'Contrato de audio seguro v2: límites, AAD, vector y aislamiento correctos.' -ForegroundColor Green
