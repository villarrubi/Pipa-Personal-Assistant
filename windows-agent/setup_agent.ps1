[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$SkipDependencies,
    [switch]$SkipTask
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This script is deliberately per-user. It never requests elevation and keeps
# the interpreter and packages inside the repository's ignored .venv folder.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$agentDirectory = Join-Path $repoRoot 'windows-agent'
$requirementsPath = Join-Path $agentDirectory 'requirements.txt'
$venvDirectory = Join-Path $agentDirectory '.venv'
$venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
$venvPythonw = Join-Path $venvDirectory 'Scripts\pythonw.exe'
$taskInstaller = Join-Path $agentDirectory 'install_agent_task.ps1'
$statusScript = Join-Path $agentDirectory 'check_agent_status.ps1'

foreach ($requiredPath in @($requirementsPath, $taskInstaller, $statusScript)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Missing required Pipa file: $requiredPath"
    }
}

function Get-PythonLauncher {
    $py = Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $py) {
        return @($py.Source, '-3.12')
    }

    $python = Get-Command 'python.exe' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $python) {
        return @($python.Source)
    }

    throw 'Python 3.12 was not found. Install Python 3.12 and enable the py launcher.'
}

function Invoke-Python {
    param(
        [Parameter(Mandatory)] [string[]]$Launcher,
        [Parameter(Mandatory)] [string[]]$Arguments
    )

    $executable = $Launcher[0]
    $prefix = @()
    if ($Launcher.Count -gt 1) {
        $prefix = @($Launcher[1..($Launcher.Count - 1)])
    }
    $output = @(& $executable @prefix @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($output -join ' ')"
    }
    return $output
}

function Test-Python312 {
    param([Parameter(Mandatory)] [string[]]$Launcher)

    $versionOutput = Invoke-Python -Launcher $Launcher -Arguments @('--version')
    $version = ($versionOutput -join ' ').Trim()
    if ($version -notmatch '(?i)Python\s+3\.12(?:\.\d+)?') {
        throw "Pipa requires Python 3.12; selected interpreter reports $version."
    }
}

if ((Test-Path -LiteralPath $venvDirectory) -and
    (-not (Test-Path -LiteralPath $venvPython -PathType Leaf) -or
     -not (Test-Path -LiteralPath $venvPythonw -PathType Leaf))) {
    throw "The existing venv is incomplete: $venvDirectory. Repair it manually; this script never deletes it."
}

$createdVenv = $false
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $bootstrap = Get-PythonLauncher
    Test-Python312 -Launcher $bootstrap
    if ($PSCmdlet.ShouldProcess($venvDirectory, 'Create the Pipa Python virtual environment')) {
        Invoke-Python -Launcher $bootstrap -Arguments @('-m', 'venv', $venvDirectory) | Out-Host
        $createdVenv = $true
    } else {
        Write-Host 'WhatIf: virtual environment was not created; no further setup was run.'
        exit 0
    }
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf) -or
    -not (Test-Path -LiteralPath $venvPythonw -PathType Leaf)) {
    if ($createdVenv) {
        throw 'The virtual environment was not created with both python.exe and pythonw.exe.'
    }
    throw "Missing virtual-environment interpreter: $venvPython"
}

if ($WhatIfPreference) {
    if (-not $SkipDependencies) {
        $null = $PSCmdlet.ShouldProcess($requirementsPath, 'Install pinned Pipa dependencies')
    }
    if (-not $SkipTask) {
        $null = $PSCmdlet.ShouldProcess('Pipa Windows Agent', 'Register the hidden per-user logon task')
    }
    Write-Host 'WhatIf: no dependencies, task or agent process was changed.'
    exit 0
}

if (-not $SkipDependencies) {
    if ($PSCmdlet.ShouldProcess($requirementsPath, 'Install pinned Pipa dependencies')) {
        Invoke-Python -Launcher @($venvPython) -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input',
            '--requirement', $requirementsPath
        ) | Out-Host
    }
}

Invoke-Python -Launcher @($venvPython) -Arguments @(
    (Join-Path $agentDirectory 'pipa_cli.py'),
    'local-self-test'
) | Out-Host

if (-not $SkipTask) {
    if ($PSCmdlet.ShouldProcess('Pipa Windows Agent', 'Register the hidden per-user logon task')) {
        & $taskInstaller -Confirm:$false
        if ($LASTEXITCODE -ne 0) {
            throw "The agent task installer failed with exit code $LASTEXITCODE."
        }
    }
}

Write-Host 'Pipa agent setup OK.' -ForegroundColor Green
Write-Host ("Python: {0}" -f $venvPython)
Write-Host ("Task: {0}" -f $(if ($SkipTask) { 'not changed (-SkipTask)' } else { 'checked/updated for current user' }))
Write-Host 'Next diagnostic: .\windows-agent\pipa_cli.py doctor'
