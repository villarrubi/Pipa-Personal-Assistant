[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^COM[1-9][0-9]{0,2}$')]
    [string]$Port,

    [ValidateSet('waveshare-185c', 'waveshare-185c-v1')]
    [string]$Environment = 'waveshare-185c',

    [ValidateRange(0.5, 120)]
    [double]$ProbeDuration = 8,

    [ValidateSet(1, 2)]
    [int]$ExpectedBoardRevision = 2,

    [switch]$AllowDevelopmentFirmware
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$firmwarePath = Join-Path $repoRoot 'firmware'
$checkPath = Join-Path $repoRoot 'windows-agent/pipa_hardware_check.py'
$securityCheckPath = Join-Path $repoRoot 'windows-agent/firmware_security_check.py'
$pioPath = Join-Path $firmwarePath '.venv/Scripts/pio.exe'

if (-not $AllowDevelopmentFirmware) {
    throw 'Las imagenes Waveshare disponibles son de desarrollo: no incluyen Secure Boot ni cifrado de Flash. Repite con -AllowDevelopmentFirmware solo para la validacion inicial del hardware.'
}

if ($Environment -eq 'waveshare-185c' -and $ExpectedBoardRevision -ne 2) {
    throw 'El entorno waveshare-185c requiere ExpectedBoardRevision 2.'
}
if ($Environment -eq 'waveshare-185c-v1' -and $ExpectedBoardRevision -ne 1) {
    throw 'El entorno waveshare-185c-v1 requiere ExpectedBoardRevision 1.'
}
if (-not (Test-Path -LiteralPath $checkPath -PathType Leaf)) {
    throw 'Falta la comprobacion de hardware de Waveshare.'
}
if (-not (Test-Path -LiteralPath $securityCheckPath -PathType Leaf)) {
    throw 'Falta la comprobacion de seguridad eFuse.'
}
if (-not (Test-Path -LiteralPath $pioPath -PathType Leaf)) {
    throw 'Falta PlatformIO en firmware/.venv; instala la dependencia fijada antes de flashear.'
}

$pythonPath = Join-Path $repoRoot 'windows-agent/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    $pythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $pythonCommand) {
        throw 'No se encontro Python para comprobar la placa.'
    }
    $pythonPath = $pythonCommand.Source
}

Write-Host "Sonda pasiva: $Port (revision V$ExpectedBoardRevision)" -ForegroundColor Cyan
$probeOutput = @(& $pythonPath -B $checkPath --port $Port --duration $ProbeDuration `
    --expected-board-revision $ExpectedBoardRevision --json 2>&1)
$probeExitCode = $LASTEXITCODE
if ($probeExitCode -ne 0) {
    Write-Host 'La sonda no confirma la placa esperada; no se ha compilado ni flasheado nada.' -ForegroundColor Yellow
    $probeOutput | ForEach-Object { Write-Host $_ }
    exit $probeExitCode
}

try {
    $probeReport = ($probeOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'La sonda devolvio un informe no valido; no se ha flasheado nada.'
}
if ($null -eq $probeReport -or $probeReport.success -ne $true) {
    throw 'La sonda no confirma la placa esperada; no se ha flasheado nada.'
}

Write-Host "Hardware validado; se usara el entorno $Environment." -ForegroundColor Green
Write-Host 'Aviso: se ha aceptado explicitamente firmware de desarrollo; no es una imagen de produccion segura.' -ForegroundColor Yellow
Write-Host 'Las variantes secure-session-vector, secure-session-v2 y audio-i2s-lab no se pueden flashear con este script.'

$previousPlatformioCore = [Environment]::GetEnvironmentVariable('PLATFORMIO_CORE_DIR', 'Process')
try {
    $env:PLATFORMIO_CORE_DIR = Join-Path $repoRoot '.platformio-preflight'
    $buildArguments = @('run', '-d', $firmwarePath, '-e', $Environment)
    & $pioPath @buildArguments
    if ($LASTEXITCODE -ne 0) {
        throw "La compilacion del entorno $Environment ha fallado; no se ha flasheado nada."
    }

    $toolPythonPath = Join-Path $repoRoot '.platformio-preflight/penv/Scripts/python.exe'
    $espefusePath = Join-Path $repoRoot '.platformio-preflight/packages/tool-esptoolpy/espefuse.py'
    if (-not (Test-Path -LiteralPath $toolPythonPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $espefusePath -PathType Leaf)) {
        throw 'Falta el entorno espefuse de PlatformIO; ejecuta primero una compilacion con la cache local.'
    }
    $securityOutput = @(& $pythonPath -B $securityCheckPath --port $Port `
        --python $toolPythonPath --espefuse $espefusePath --json 2>&1)
    $securityExitCode = $LASTEXITCODE
    if ($securityExitCode -ne 0) {
        throw 'No se ha podido confirmar que el estado eFuse sea compatible con una imagen de desarrollo; no se ha flasheado nada.'
    }
    try {
        $securityReport = ($securityOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw 'La comprobacion eFuse devolvio un informe no valido; no se ha flasheado nada.'
    }
    if ($null -eq $securityReport -or $securityReport.success -ne $true -or
        $securityReport.read_only -ne $true) {
        throw 'El estado eFuse no autoriza una imagen de desarrollo; no se ha flasheado nada.'
    }
    Write-Host 'Estado eFuse compatible; no hay Secure Boot, cifrado de Flash ni anti-rollback activo.' -ForegroundColor Yellow

    $uploadArguments = @(
        'run', '-d', $firmwarePath, '-e', $Environment,
        '-t', 'upload', '--upload-port', $Port
    )
    if ($PSCmdlet.ShouldProcess("Waveshare en $Port", "Flashear entorno $Environment")) {
        & $pioPath @uploadArguments
        if ($LASTEXITCODE -ne 0) {
            throw "El flasheo del entorno $Environment ha fallado."
        }
        Write-Host 'Firmware cargado. Reinicia la placa y conserva solo los logs revisados del monitor serie.' -ForegroundColor Green
    } else {
        Write-Host 'WhatIf: no se ha flasheado la placa.' -ForegroundColor Yellow
    }
} finally {
    if ($null -eq $previousPlatformioCore) {
        Remove-Item Env:PLATFORMIO_CORE_DIR -ErrorAction SilentlyContinue
    } else {
        $env:PLATFORMIO_CORE_DIR = $previousPlatformioCore
    }
}
