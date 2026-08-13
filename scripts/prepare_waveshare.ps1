[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^COM[1-9][0-9]{0,2}$')]
    [string]$Port,

    [ValidateRange(0.5, 120)]
    [double]$Duration = 8,

    [ValidateSet(1, 2)]
    [int]$ExpectedBoardRevision = 2,

    [switch]$RestartAgent
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$checkPath = Join-Path $repoRoot 'windows-agent/pipa_hardware_check.py'
$launcherPath = Join-Path $repoRoot 'windows-agent/start_agent_hidden.ps1'

function Find-Python {
    $venvPython = Join-Path $repoRoot 'windows-agent/.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }
    $command = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $command) {
        return $command.Source
    }
    throw 'No se encontro Python. Instala windows-agent/.venv o Python en PATH.'
}

if (-not (Test-Path -LiteralPath $checkPath -PathType Leaf)) {
    throw 'Falta la comprobacion de hardware de Waveshare.'
}

$python = Find-Python
$output = @(& $python -B $checkPath --port $Port --duration $Duration `
    --expected-board-revision $ExpectedBoardRevision --json 2>&1)
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Host 'La sonda de hardware no ha sido satisfactoria; no se ha cambiado la configuracion.' -ForegroundColor Yellow
    $output | ForEach-Object { Write-Host $_ }
    exit $exitCode
}

try {
    $report = ($output -join "`n") | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'La sonda de hardware devolvio un informe no valido; no se ha cambiado la configuracion.'
}

if ($null -eq $report -or $report.success -ne $true) {
    throw 'La sonda no confirma la placa esperada; no se ha cambiado la configuracion.'
}

Write-Host ("Hardware Waveshare validado en {0}; revision V{1}." -f $Port, $ExpectedBoardRevision) -ForegroundColor Green
Write-Host 'La sonda fue pasiva: no envio comandos, no activo Wake-on-LAN y no emparejo ninguna clave.'

if ($PSCmdlet.ShouldProcess('PIPA_SERIAL_PORT del usuario', "establecer $Port")) {
    [Environment]::SetEnvironmentVariable('PIPA_SERIAL_PORT', $Port, 'User')
    Write-Host ("PIPA_SERIAL_PORT establecido para el usuario: {0}" -f $Port) -ForegroundColor Green
}

if ($RestartAgent) {
    if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
        throw 'No se encontro el lanzador oculto del agente.'
    }
    if ($PSCmdlet.ShouldProcess('agente Pipa', 'reiniciar con el nuevo puerto')) {
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $launcherPath -Restart
        if ($LASTEXITCODE -ne 0) {
            throw 'El agente no pudo reiniciarse correctamente.'
        }
    }
}

Write-Host ''
Write-Host 'Siguiente paso: obtener la clave publica del monitor, comparar su fingerprint por un canal fisico y ejecutar pair.' -ForegroundColor Cyan
Write-Host 'La sesion segura v2 y Trusted Unlock siguen desactivados.' -ForegroundColor Cyan
