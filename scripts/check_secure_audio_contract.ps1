[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $repoRoot 'windows-agent/secure_audio.py'
$pythonTestPath = Join-Path $repoRoot 'windows-agent/tests/test_secure_audio.py'
$swiftPath = Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaSecureAudio.swift'
$fixturePath = Join-Path $repoRoot 'mobile-ios/Tests/Fixtures/secure_audio_v2.json'
$firmwareSessionPath = Join-Path $repoRoot 'firmware/src/pipa_secure_session.cpp'
$firmwareAudioHeaderPath = Join-Path $repoRoot 'firmware/src/pipa_secure_audio.h'
$firmwareAudioPath = Join-Path $repoRoot 'firmware/src/pipa_secure_audio.cpp'
$firmwareMainPath = Join-Path $repoRoot 'firmware/src/main.cpp'

foreach ($path in @($pythonPath, $pythonTestPath, $swiftPath, $fixturePath, $firmwareSessionPath, $firmwareAudioHeaderPath, $firmwareAudioPath, $firmwareMainPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta un artefacto del contrato de audio seguro: $path"
    }
}

$python = Get-Content -LiteralPath $pythonPath -Raw
$swift = Get-Content -LiteralPath $swiftPath -Raw
$fixture = Get-Content -LiteralPath $fixturePath -Raw
$firmwareSession = Get-Content -LiteralPath $firmwareSessionPath -Raw
$firmwareAudioHeader = Get-Content -LiteralPath $firmwareAudioHeaderPath -Raw
$firmwareAudio = Get-Content -LiteralPath $firmwareAudioPath -Raw
$firmwareMain = Get-Content -LiteralPath $firmwareMainPath -Raw
$fixtureObject = $fixture | ConvertFrom-Json

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
    'kMaxChunkBytes = 4096',
    'kMaxChunks = 64',
    'kMaxStreamBytes = kMaxChunkBytes * kMaxChunks',
    'kMaxStreamIdLength = 64',
    'kMaxAdditionalDataBytes = 1024'
)) {
    if ($firmwareAudioHeader.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El header C++ no contiene el límite compartido: $required"
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
if ($firmwareAudio.IndexOf('pipa/audio/v2', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El vector de firmware no contiene el AAD de audio v2 compartido.'
}
if ($firmwareAudio.IndexOf('pipa/audio/v2', [System.StringComparison]::Ordinal) -lt 0 -or
    $firmwareAudioHeader.IndexOf('PipaSecureAudioSender', [System.StringComparison]::Ordinal) -lt 0 -or
    $firmwareAudioHeader.IndexOf('PipaSecureAudioReceiver', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El primitive de framing del firmware no contiene el contrato esperado.'
}
if ($firmwareAudio -match '(?im)#include\s*[<"](?:driver/i2s|I2S|Wire|WiFi|Bluetooth|esp_audio)[>"]|\b(?:Wire|Serial|WiFi)\s*[.(]|\b(?:ES8311|ES7210)\b') {
    throw 'El framing de audio del firmware no puede depender de hardware, red ni puertos.'
}
$vectorGuard = '(?s)#if\s+defined\(PIPA_SECURE_SESSION_VECTOR_TEST\).*?PipaSecureAudio::vectorSelfTest\(\).*?#endif'
if ($firmwareMain -notmatch $vectorGuard) {
    throw 'La prueba de audio del firmware debe quedar protegida por PIPA_SECURE_SESSION_VECTOR_TEST.'
}
if ($fixture -notmatch '"ciphertext"\s*:\s*"[^"\r\n]+"' -or
    $fixture -match '(?s)"frame"\s*:\s*\{[^}]*"samples"\s*:') {
    throw 'El vector debe contener ciphertext y no puede transportar samples dentro de la trama.'
}

if ($fixtureObject.frame.audio_protocol_version -ne 2 -or
    $fixtureObject.frame.bits_per_sample -ne 16 -or
    $fixtureObject.frame.channels -ne 1 -or
    $fixtureObject.frame.sample_rate -ne 16000 -or
    $fixtureObject.frame.chunk_index -ne 0 -or
    $fixtureObject.frame.final -ne $true -or
    $fixtureObject.frame.stream_id -ne $fixtureObject.stream_id) {
    throw 'El fixture de audio no conserva el perfil PCM v2 esperado.'
}

function ConvertFrom-Base64Url {
    param([Parameter(Mandatory)] [string]$Value)

    $base64 = $Value.Replace('-', '+').Replace('_', '/')
    switch ($base64.Length % 4) {
        0 { }
        2 { $base64 += '==' }
        3 { $base64 += '=' }
        default { throw 'El ciphertext base64url del fixture tiene una longitud inválida.' }
    }
    return [Convert]::FromBase64String($base64)
}

$fixtureCiphertext = ConvertFrom-Base64Url $fixtureObject.frame.ciphertext
$firmwareVectorMatch = [regex]::Match(
    $firmwareAudio,
    '(?s)expected_ciphertext_and_tag\[\]\s*=\s*\{(?<bytes>.*?)\};')
if (-not $firmwareVectorMatch.Success) {
    throw 'El vector C++ no contiene su ciphertext esperado en una forma verificable.'
}
$firmwareBytes = @(
    [regex]::Matches($firmwareVectorMatch.Groups['bytes'].Value, '0x(?<byte>[0-9A-Fa-f]{2})') |
        ForEach-Object { $_.Groups['byte'].Value.ToUpperInvariant() }
)
$fixtureHex = (($fixtureCiphertext | ForEach-Object { $_.ToString('X2') }) -join '')
$firmwareHex = ($firmwareBytes -join '')
if ($fixtureHex -ne $firmwareHex) {
    throw 'El ciphertext del vector firmware no coincide con el fixture compartido.'
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

$productionFirmware = @(Get-ChildItem -Path (Join-Path $repoRoot 'firmware/src') -Include '*.cpp', '*.h' -File -Recurse | Where-Object {
    $_.FullName -ne $firmwareAudioHeaderPath -and
    $_.FullName -ne $firmwareAudioPath
})
foreach ($path in $productionFirmware) {
    $source = Get-Content -LiteralPath $path.FullName -Raw
    if ($path.FullName -eq $firmwareMainPath) {
        $source = [regex]::Replace($source, $vectorGuard, '')
        $source = $source -replace '(?m)^\s*#include\s*[<"]pipa_secure_audio\.h[>"]\s*$', ''
    }
    if ($source -match '(?i)PipaSecureAudio|secure_audio|pipa/audio/v2') {
        throw "El audio seguro no puede conectarse aún al firmware de producción: $($path.FullName)"
    }
}

Write-Host 'Contrato de audio seguro v2: límites, AAD, vector y aislamiento correctos.' -ForegroundColor Green
