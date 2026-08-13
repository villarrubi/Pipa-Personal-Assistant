[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pinMapPath = Join-Path $repoRoot 'firmware/src/board_pins.h'
$vendorFiles = @(
    'firmware/src/vendor/esp_lcd_st77916.c',
    'firmware/src/vendor/esp_lcd_st77916.h'
)

if (-not (Test-Path -LiteralPath $pinMapPath -PathType Leaf)) {
    throw "Falta el mapa de pines: $pinMapPath"
}
foreach ($relativePath in $vendorFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Falta el driver de pantalla revisado: $relativePath"
    }
}

$pinMap = Get-Content -LiteralPath $pinMapPath -Raw
$v2Match = [regex]::Match($pinMap, '(?s)#if PIPA_BOARD_REVISION == 2(.*?)#elif PIPA_BOARD_REVISION == 1')
$v1Match = [regex]::Match($pinMap, '(?s)#elif PIPA_BOARD_REVISION == 1(.*?)#else')
if (-not $v2Match.Success -or -not $v1Match.Success) {
    throw 'No se pueden separar las secciones V1 y V2 del mapa de pines.'
}

$expectedV2 = @(
    'kI2cSda = 11',
    'kI2cScl = 10',
    'kBatteryAdc = 8',
    'kTouchInterrupt = 4',
    'kTouchResetExpander = 1',
    'kDisplayResetExpander = 2',
    'kDisplaySck = 40',
    'kDisplayData0 = 46',
    'kDisplayData1 = 45',
    'kDisplayData2 = 42',
    'kDisplayData3 = 41',
    'kDisplayCs = 21',
    'kDisplayTearingEffect = 18',
    'kDisplayBacklight = 5',
    'kAmplifierEnable = 15',
    'kI2sMclk = 2',
    'kI2sBclk = 48',
    'kI2sLrck = 38',
    'kI2sDataIn = 47',
    'kI2sMicData = 39'
)
$expectedV1 = @(
    'kI2cSda = 3',
    'kI2cScl = 1',
    'kBatteryAdc = kNoPin',
    'kTouchInterrupt = 4',
    'kTouchResetExpander = 1',
    'kDisplayResetExpander = 2',
    'kDisplaySck = 40',
    'kDisplayData0 = 46',
    'kDisplayData1 = 45',
    'kDisplayData2 = 42',
    'kDisplayData3 = 41',
    'kDisplayCs = 21',
    'kDisplayTearingEffect = 18',
    'kDisplayBacklight = 5',
    'kAmplifierEnable = kNoPin',
    'kI2sMclk = kNoPin',
    'kI2sBclk = 48',
    'kI2sLrck = 38',
    'kI2sDataIn = 47',
    'kI2sMicData = 39'
)

foreach ($pattern in $expectedV2) {
    if ($v2Match.Groups[1].Value.IndexOf($pattern, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El mapa V2 no coincide con la referencia revisada: $pattern"
    }
}
foreach ($pattern in $expectedV1) {
    if ($v1Match.Groups[1].Value.IndexOf($pattern, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El mapa V1 no coincide con la referencia de compatibilidad: $pattern"
    }
}

Write-Host 'Mapa Waveshare V1/V2 OK: GPIO, expander, QSPI e I2S revisados.' -ForegroundColor Green
