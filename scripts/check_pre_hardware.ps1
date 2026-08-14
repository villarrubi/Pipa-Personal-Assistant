[CmdletBinding()]
param(
    [switch]$SkipResidentAgent
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$failures = [System.Collections.Generic.List[string]]::new()

function Write-CheckResult {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [bool]$Success,
        [string]$Detail = ''
    )

    if ($Success) {
        Write-Host ("[OK] {0}{1}" -f $Name, $Detail) -ForegroundColor Green
    } else {
        Write-Host ("[FAIL] {0}{1}" -f $Name, $Detail) -ForegroundColor Red
        $failures.Add($Name)
    }
}

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
    return $null
}

function Invoke-PipaJsonCheck {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$Python,
        [Parameter(Mandatory)] [string[]]$Arguments
    )

    try {
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = @(& $Python @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorAction
        }
        if ($exitCode -ne 0) {
            Write-CheckResult -Name $Name -Success $false -Detail (" (exit {0})" -f $exitCode)
            return
        }
        $json = ($output -join "`n") | ConvertFrom-Json -ErrorAction Stop
        $success = $null -ne $json -and $json.success -eq $true
        Write-CheckResult -Name $Name -Success $success
    } catch {
        Write-CheckResult -Name $Name -Success $false -Detail ' (invalid or unavailable result)'
    }
}

Write-Host 'Pipa pre-hardware gate' -ForegroundColor Cyan
Write-Host ("Repository: {0}" -f $repoRoot)

$logSafetyScript = Join-Path $repoRoot 'scripts/check_log_safety.ps1'
try {
    & $logSafetyScript
    Write-CheckResult -Name 'Runtime log safety' -Success ($LASTEXITCODE -eq 0)
} catch {
    Write-CheckResult -Name 'Runtime log safety' -Success $false
}

$python = Find-Python
if ($null -eq $python) {
    Write-CheckResult -Name 'Python runtime' -Success $false -Detail ' (python not found)'
} else {
    $cli = Join-Path $repoRoot 'windows-agent/pipa_cli.py'
    Invoke-PipaJsonCheck -Name 'Current-source self-test' -Python $python -Arguments @(
        '-B', $cli, 'local-self-test'
    )
    Invoke-PipaJsonCheck -Name 'Current-source capabilities' -Python $python -Arguments @(
        '-B', $cli, 'local-capabilities'
    )
    Invoke-PipaJsonCheck -Name 'Integration protocol simulator' -Python $python -Arguments @(
        '-B', $cli, 'integration-protocol-test'
    )
    Invoke-PipaJsonCheck -Name 'Secure protocol self-test' -Python $python -Arguments @(
        '-B', $cli, 'secure-test'
    )
    Invoke-PipaJsonCheck -Name 'Mobile protocol self-test' -Python $python -Arguments @(
        '-B', $cli, 'mobile-test'
    )
    Invoke-PipaJsonCheck -Name 'Mobile TCP loopback self-test' -Python $python -Arguments @(
        '-B', $cli, 'mobile-tcp-test'
    )
    Invoke-PipaJsonCheck -Name 'Mobile configuration safety' -Python $python -Arguments @(
        '-B', $cli, 'mobile-config'
    )

    $hardwareChecker = Join-Path $repoRoot 'windows-agent/pipa_hardware_check.py'
    $hardwareFixture = Join-Path $repoRoot 'windows-agent/tests/fixtures/waveshare-v2-boot.txt'
    if ((Test-Path -LiteralPath $hardwareChecker -PathType Leaf) -and
        (Test-Path -LiteralPath $hardwareFixture -PathType Leaf)) {
        Invoke-PipaJsonCheck -Name 'Waveshare diagnostic parser fixture' -Python $python -Arguments @(
            '-B', $hardwareChecker, '--fixture', $hardwareFixture, '--json'
        )
    } else {
        Write-CheckResult -Name 'Waveshare diagnostic parser fixture' -Success $false -Detail ' (fixture or checker missing)'
    }

    if (-not $SkipResidentAgent) {
        Invoke-PipaJsonCheck -Name 'Resident agent doctor' -Python $python -Arguments @(
            '-B', $cli, 'doctor'
        )
    }
}

$scriptPath = $MyInvocation.MyCommand.Path
if (-not [string]::IsNullOrWhiteSpace($scriptPath) -and
    (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    Write-CheckResult -Name 'Pre-hardware gate script' -Success $true
} else {
    Write-CheckResult -Name 'Pre-hardware gate script' -Success $false
}

Write-Host ''
if ($failures.Count -eq 0) {
    Write-Host 'Checks failed: 0' -ForegroundColor Green
} else {
    Write-Host ("Checks failed: {0}" -f $failures.Count) -ForegroundColor Red
}

if ($failures.Count -gt 0) {
    exit 1
}
exit 0
