[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sourcePath = Join-Path $repoRoot 'firmware/src/pipa_audio_i2s_lab.cpp'
$headerPath = Join-Path $repoRoot 'firmware/src/pipa_audio_i2s_lab.h'
$mainPath = Join-Path $repoRoot 'firmware/src/main.cpp'
$platformioPath = Join-Path $repoRoot 'firmware/platformio.ini'

foreach ($path in @($sourcePath, $headerPath, $mainPath, $platformioPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta un artefacto de la sonda I2S: $path"
    }
}

$source = Get-Content -LiteralPath $sourcePath -Raw
$header = Get-Content -LiteralPath $headerPath -Raw
$main = Get-Content -LiteralPath $mainPath -Raw
$platformio = Get-Content -LiteralPath $platformioPath -Raw

if ($platformio.IndexOf('[env:audio-i2s-lab]', [System.StringComparison]::Ordinal) -lt 0 -or
    $platformio.IndexOf('-DPIPA_AUDIO_I2S_LAB=1', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El entorno audio-i2s-lab no está explícitamente aislado.'
}
if ($header.IndexOf('read', [System.StringComparison]::OrdinalIgnoreCase) -lt 0 -or
    $header.IndexOf('write', [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
    throw 'La documentación de la sonda debe declarar que no lee ni escribe muestras.'
}
if ($source -match '(?i)\.(read|readBytes|write)\s*\(') {
    throw 'La sonda I2S no puede leer ni escribir muestras.'
}
if ($source -match '(?i)digitalWrite\s*\([^,]+,\s*HIGH') {
    throw 'La sonda I2S no puede activar el amplificador.'
}
if ($source -match '(?i)es8311|es7210|recordWAV|playWAV') {
    throw 'La sonda I2S no puede configurar codecs ni grabar/reproducir audio.'
}
if ($main.IndexOf('PipaAudioI2sLab', [System.StringComparison]::Ordinal) -ge 0) {
    throw 'El firmware normal no puede conectar la sonda I2S experimental al main.'
}
if ($source.IndexOf('PIPA_SECURE_SESSION_ENABLED', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'La sonda debe mantener una barrera explícita frente al entorno seguro.'
}

Write-Host 'Sonda audio-i2s-lab segura: compilación experimental aislada, sin muestras, codec ni amplificador.' -ForegroundColor Green
