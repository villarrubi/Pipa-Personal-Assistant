[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$headerPath = Join-Path $repoRoot 'firmware/src/pipa_audio_state.h'
$sourcePath = Join-Path $repoRoot 'firmware/src/pipa_audio_state.cpp'
$audioHeaderPath = Join-Path $repoRoot 'firmware/src/pipa_audio.h'
$audioSourcePath = Join-Path $repoRoot 'firmware/src/pipa_audio.cpp'
$hostTestPath = Join-Path $repoRoot 'firmware/tests/pipa_audio_state_host_test.cpp'
$mainPath = Join-Path $repoRoot 'firmware/src/main.cpp'

foreach ($path in @($headerPath, $sourcePath, $audioHeaderPath, $audioSourcePath, $hostTestPath, $mainPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta un artefacto de la compuerta de audio: $path"
    }
}

$header = Get-Content -LiteralPath $headerPath -Raw
$source = Get-Content -LiteralPath $sourcePath -Raw
$audioHeader = Get-Content -LiteralPath $audioHeaderPath -Raw
$audioSource = Get-Content -LiteralPath $audioSourcePath -Raw
$hostTest = Get-Content -LiteralPath $hostTestPath -Raw
$main = Get-Content -LiteralPath $mainPath -Raw

foreach ($required in @(
    'kDisabled', 'kProbeOnly', 'kCodecReady', 'kListening', 'kDraining', 'kError',
    'beginProbe', 'markCodecReady', 'beginListening', 'beginDraining', 'finishDraining',
    'canAdvertiseAudio', 'canCapture', 'vectorSelfTest'
)) {
    if ($header.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0 -and
        $source.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0) {
        throw "La compuerta de audio no contiene la transición requerida: $required"
    }
}

foreach ($path in @($headerPath, $sourcePath)) {
    $stateSource = Get-Content -LiteralPath $path -Raw
    $stateSource = [regex]::Replace($stateSource, '(?m)^\s*//.*$', '')
    $stateSource = [regex]::Replace($stateSource, '(?s)/\*.*?\*/', '')
    if ($stateSource -match '(?i)#include\s*[<"](?:Arduino|Wire|ESP_I2S|driver/i2s|WiFi|Serial)[>"]') {
        throw "La máquina de estados no puede depender de hardware o transporte: $path"
    }
}

if ($audioHeader.IndexOf('pipa_audio_state.h', [System.StringComparison]::Ordinal) -lt 0 -or
    $audioSource.IndexOf('state_machine_.beginProbe()', [System.StringComparison]::Ordinal) -lt 0 -or
    $audioSource.IndexOf('status_.state', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'La sonda física no está conectada a la compuerta de estado.'
}
if ($hostTest.IndexOf('PipaAudioStateMachine::vectorSelfTest()', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'Falta la ejecución host del vector de la compuerta de audio.'
}

$vectorGuard = '(?s)#if\s+defined\(PIPA_SECURE_SESSION_VECTOR_TEST\).*?PipaAudioStateMachine::vectorSelfTest\(\).*?#endif'
if ($main -notmatch $vectorGuard) {
    throw 'El vector de la compuerta debe ejecutarse solo en secure-session-vector.'
}
$normalMain = [regex]::Replace($main, $vectorGuard, '')
if ($normalMain -match '(?i)beginListening\(|markCodecReady\(') {
    throw 'El firmware normal no puede activar escucha ni declarar codec listo todavía.'
}

Write-Host 'Compuerta de estados de audio: transiciones, aislamiento y vector correctos.' -ForegroundColor Green
