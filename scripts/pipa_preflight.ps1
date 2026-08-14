[CmdletBinding()]
param(
    [switch]$SkipPythonTests,
    [switch]$CheckFirmware,
    [switch]$RequireHardware,
    [switch]$SkipStartupCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
$env:RUFF_CACHE_DIR = Join-Path $repoRoot '.ruff_cache'

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

function Invoke-ExternalCheck {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$Arguments
    )

    $command = Get-Command $FilePath -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $command) {
        Write-CheckResult -Name $Name -Success $false -Detail ' (command not found)'
        return
    }

    try {
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = @(& $command.Source @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorAction
        }
    } catch {
        Write-CheckResult -Name $Name -Success $false -Detail ' (execution failed)'
        return
    }
    if ($exitCode -ne 0) {
        Write-CheckResult -Name $Name -Success $false -Detail (" (exit {0})" -f $exitCode)
        return
    }
    Write-CheckResult -Name $Name -Success $true
}

function Invoke-RepoScriptCheck {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$RelativePath
    )

    $scriptPath = Join-Path $repoRoot ($RelativePath -replace '/', '\')
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        Write-CheckResult -Name $Name -Success $false -Detail ' (script missing)'
        return
    }
    Invoke-ExternalCheck -Name $Name -FilePath 'powershell.exe' -Arguments @(
        '-NoLogo',
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $scriptPath
    )
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
    return 'python'
}

Write-Host 'Pipa preflight' -ForegroundColor Cyan
Write-Host ("Repository: {0}" -f $repoRoot)
$python = Find-Python
Write-Host ("Python: {0}" -f $python) -ForegroundColor DarkCyan

Invoke-RepoScriptCheck -Name 'PowerShell syntax' -RelativePath 'scripts/check_powershell_syntax.ps1'
Invoke-RepoScriptCheck -Name 'Workflow action pinning' -RelativePath 'scripts/check_workflow_security.ps1'
Invoke-RepoScriptCheck -Name 'CI coverage' -RelativePath 'scripts/check_ci_coverage.ps1'
Invoke-RepoScriptCheck -Name 'Agent startup lifecycle' -RelativePath 'scripts/check_agent_startup.ps1'
Invoke-RepoScriptCheck -Name 'Repository hygiene and ignore policy' -RelativePath 'scripts/check_repo_hygiene.ps1'
Invoke-RepoScriptCheck -Name 'Git history audit' -RelativePath 'scripts/check_git_history.ps1'
Invoke-RepoScriptCheck -Name 'Secret pattern self-test' -RelativePath 'scripts/test_security_patterns.ps1'
Invoke-RepoScriptCheck -Name 'iOS package structure' -RelativePath 'scripts/check_mobile_ios_package.ps1'
Invoke-ExternalCheck -Name 'Mobile capability contract' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'scripts/check_mobile_capability_contract.py')
)
Invoke-ExternalCheck -Name 'Mobile catalog contract' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'scripts/check_mobile_catalog_contract.py')
)
Invoke-ExternalCheck -Name 'Mobile confirmation contract' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'scripts/check_mobile_confirmation_contract.py')
)
Invoke-ExternalCheck -Name 'Mobile safety contract' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'scripts/check_mobile_safety_contract.py')
)
Invoke-RepoScriptCheck -Name 'Waveshare V1/V2 pin map' -RelativePath 'scripts/check_waveshare_pinmap.ps1'
Invoke-RepoScriptCheck -Name 'Firmware configuration safety' -RelativePath 'scripts/check_firmware_config.ps1'
Invoke-RepoScriptCheck -Name 'Firmware flashing safety' -RelativePath 'scripts/check_firmware_flash_safety.ps1'
Invoke-RepoScriptCheck -Name 'Firmware eFuse security gate' -RelativePath 'scripts/check_firmware_security_gate.ps1'
Invoke-RepoScriptCheck -Name 'Firmware log safety' -RelativePath 'scripts/check_firmware_log_safety.ps1'
Invoke-RepoScriptCheck -Name 'Secure handshake contract' -RelativePath 'scripts/check_secure_handshake_contract.ps1'
Invoke-RepoScriptCheck -Name 'Trusted Unlock safety' -RelativePath 'scripts/check_trusted_unlock_safety.ps1'
Invoke-RepoScriptCheck -Name 'Secure audio contract isolation' -RelativePath 'scripts/check_secure_audio_contract.ps1'
Invoke-RepoScriptCheck -Name 'Audio state machine isolation' -RelativePath 'scripts/check_audio_state_machine.ps1'
Invoke-RepoScriptCheck -Name 'Display text isolation' -RelativePath 'scripts/check_display_text.ps1'

if ($SkipStartupCheck) {
    Write-Host '[INFO] Hidden startup and local agent check skipped explicitly.' -ForegroundColor Yellow
    $warnings.Add('Hidden startup and local agent check was skipped.')
} else {
    $statusPath = Join-Path $repoRoot 'windows-agent/check_agent_status.ps1'
    if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
        try {
            $statusOutput = @(& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $statusPath 2>&1)
            $statusCode = $LASTEXITCODE
            $statusText = $statusOutput -join "`n"
            $statusSafe =
                $statusCode -eq 0 -and
                $statusText -match 'Agente:\s+online' -and
                $statusText -match 'Perfil inicio oculto/limitado:\s+OK' -and
                ($statusText -match 'Fallback de inicio:\s+ninguno' -or
                 $statusText -match 'Perfil inicio oculto/limitado:\s+OK \(fallback (HKCU|Startup)\)')
            $statusDetail = ''
            if ($statusCode -ne 0) {
                $statusDetail = ' (el diagnostico no pudo ejecutarse)'
            } elseif ($statusText -notmatch 'Agente:\s+online') {
                $statusDetail = ' (agente local offline)'
            } elseif ($statusText -match 'NO VERIFICADO') {
                $statusDetail = ' (Programador de tareas inaccesible; no se pudo verificar un inicio seguro)'
            } elseif ($statusText -match 'NO INSTALADO') {
                $statusDetail = ' (no hay tarea ni fallback de inicio instalado)'
            } elseif ($statusText -match 'Fallback de inicio duplicado') {
                $statusDetail = ' (hay mas de un mecanismo de inicio)'
            }
            Write-CheckResult -Name 'Hidden startup and local agent' -Success $statusSafe -Detail $statusDetail
        } catch {
            Write-CheckResult -Name 'Hidden startup and local agent' -Success $false
        }
    } else {
        Write-CheckResult -Name 'Hidden startup and local agent' -Success $false -Detail ' (script missing)'
    }
}

$listenerAddresses = [System.Collections.Generic.List[string]]::new()
try {
    $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop)
    foreach ($listener in $listeners) {
        $listenerAddresses.Add([string]$listener.LocalAddress)
    }
} catch {
    # Some locked-down PowerShell sessions deny the NetTCPConfiguration CIM
    # query even though netstat is available. Parse only LISTENING entries for
    # this exact port; an unavailable or ambiguous result still fails closed.
    $netstatLines = @(netstat.exe -ano -p tcp 2>$null)
    foreach ($line in $netstatLines) {
        if ($line -notmatch '^\s*TCP\s+(?<local>\S+)\s+\S+\s+LISTENING\s+\d+\s*$') {
            continue
        }
        $localEndpoint = [string]$Matches.local
        if (-not $localEndpoint.EndsWith(':8765', [System.StringComparison]::Ordinal)) {
            continue
        }
        $address = $localEndpoint.Substring(0, $localEndpoint.Length - 5).TrimEnd(':')
        if ($address.StartsWith('[') -and $address.EndsWith(']')) {
            $address = $address.Substring(1, $address.Length - 2)
        }
        if (-not [string]::IsNullOrWhiteSpace($address)) {
            $listenerAddresses.Add($address)
        }
    }
}
$unsafeListeners = @(
    $listenerAddresses | Where-Object { $_ -notin @('127.0.0.1', '::1') }
)
$loopbackOnly = $listenerAddresses.Count -gt 0 -and $unsafeListeners.Count -eq 0
Write-CheckResult -Name 'Agent listens on loopback only' -Success $loopbackOnly

if (-not $SkipPythonTests) {
    Invoke-ExternalCheck -Name 'Backend tests' -FilePath $python -Arguments @(
        '-B', '-m', 'unittest', 'discover', '-s', (Join-Path $repoRoot 'backend/tests'), '-p', 'test_*.py'
    )
    Invoke-ExternalCheck -Name 'Windows Agent tests' -FilePath $python -Arguments @(
        '-B', '-m', 'unittest', 'discover', '-s', (Join-Path $repoRoot 'windows-agent/tests'), '-p', 'test_*.py'
    )
    Invoke-ExternalCheck -Name 'Python compilation' -FilePath $python -Arguments @(
        '-m', 'compileall', '-q', (Join-Path $repoRoot 'backend'), (Join-Path $repoRoot 'windows-agent'), (Join-Path $repoRoot 'scripts')
    )
}

$pythonApplication = Get-Command $python -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
$ruffAvailable = $false
if ($null -ne $pythonApplication) {
    $ruffProbe = @(& $pythonApplication.Source -m ruff --version 2>&1)
    $ruffAvailable = $LASTEXITCODE -eq 0
}
if ($ruffAvailable) {
    Invoke-ExternalCheck -Name 'Ruff lint' -FilePath $python -Arguments @('-m', 'ruff', 'check', (Join-Path $repoRoot 'backend'), (Join-Path $repoRoot 'windows-agent'), (Join-Path $repoRoot 'scripts'))
    Invoke-ExternalCheck -Name 'Ruff format' -FilePath $python -Arguments @('-m', 'ruff', 'format', '--check', (Join-Path $repoRoot 'backend'), (Join-Path $repoRoot 'windows-agent'), (Join-Path $repoRoot 'scripts'))
} elseif ($null -ne $pythonApplication) {
    $warnings.Add('Ruff is not installed; CI still checks it.')
    Write-Host '[WARN] Ruff is not installed; CI still checks it.' -ForegroundColor Yellow
}

Invoke-ExternalCheck -Name 'Agent doctor' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'doctor'
)
Invoke-ExternalCheck -Name 'Current-source integration self-test' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'local-self-test'
)
Invoke-ExternalCheck -Name 'Device protocol self-test' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'device-test'
)
Invoke-ExternalCheck -Name 'Synthetic voice transcript preview' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'voice-preview', 'estado', 'de', 'integraciones'
)
Invoke-ExternalCheck -Name 'Current-source capabilities' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'local-capabilities'
)
Invoke-ExternalCheck -Name 'Integration self-test' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'self-test'
)
Invoke-ExternalCheck -Name 'Mobile protocol self-test' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'mobile-test'
)
Invoke-ExternalCheck -Name 'Mobile TCP loopback self-test' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'mobile-tcp-test'
)
Invoke-ExternalCheck -Name 'Mobile transport configuration' -FilePath $python -Arguments @(
    (Join-Path $repoRoot 'windows-agent/pipa_cli.py'), 'mobile-config'
)

if ($CheckFirmware) {
    $pio = Join-Path $repoRoot 'firmware/.venv/Scripts/pio.exe'
    if (-not (Test-Path -LiteralPath $pio -PathType Leaf)) {
        Write-CheckResult -Name 'Firmware toolchain' -Success $false -Detail ' (firmware/.venv missing)'
    } else {
        Invoke-ExternalCheck -Name 'Audio I2S lab safety' -FilePath 'powershell.exe' -Arguments @(
            '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            (Join-Path $repoRoot 'scripts/check_audio_i2s_lab.ps1')
        )
        # Keep PlatformIO state inside the repository's ignored workspace so a
        # protected or stale user profile cannot make a valid build fail.
        $env:PLATFORMIO_CORE_DIR = Join-Path $repoRoot '.platformio-preflight'
        Invoke-ExternalCheck -Name 'Firmware V2 build' -FilePath $pio -Arguments @('run', '-d', (Join-Path $repoRoot 'firmware'), '-e', 'waveshare-185c')
        Invoke-ExternalCheck -Name 'Firmware V1 compatibility build' -FilePath $pio -Arguments @('run', '-d', (Join-Path $repoRoot 'firmware'), '-e', 'waveshare-185c-v1')
        Invoke-ExternalCheck -Name 'Firmware secure-session vector build' -FilePath $pio -Arguments @('run', '-d', (Join-Path $repoRoot 'firmware'), '-e', 'secure-session-vector')
        Invoke-ExternalCheck -Name 'Firmware audio I2S lab build' -FilePath $pio -Arguments @('run', '-d', (Join-Path $repoRoot 'firmware'), '-e', 'audio-i2s-lab')
        # Keep the local preflight on the same explicit environment used by CI.
        # This avoids leaking build flags into the caller's PowerShell session.
        Invoke-ExternalCheck -Name 'Firmware secure-session build' -FilePath $pio -Arguments @('run', '-d', (Join-Path $repoRoot 'firmware'), '-e', 'secure-session-v2')
    }
}

$serialPort = [Environment]::GetEnvironmentVariable('PIPA_SERIAL_PORT', 'Process')
if ([string]::IsNullOrWhiteSpace($serialPort)) {
    $serialPort = [Environment]::GetEnvironmentVariable('PIPA_SERIAL_PORT', 'User')
}
if ([string]::IsNullOrWhiteSpace($serialPort)) {
    Write-Host '[INFO] PIPA_SERIAL_PORT is not configured; hardware checks are pending.' -ForegroundColor DarkYellow
    if ($RequireHardware) {
        Write-CheckResult -Name 'Waveshare serial gateway' -Success $false -Detail ' (PIPA_SERIAL_PORT missing)'
    } else {
        $warnings.Add('Waveshare serial gateway is not configured yet.')
    }
} else {
    Write-Host ("[INFO] PIPA_SERIAL_PORT configured as {0}" -f $serialPort) -ForegroundColor Cyan
    if ($RequireHardware) {
        Invoke-ExternalCheck -Name 'Waveshare serial smoke check' -FilePath $python -Arguments @(
            (Join-Path $repoRoot 'windows-agent/pipa_hardware_check.py'),
            '--port', $serialPort,
            '--duration', '8'
        )
    }
}

Write-Host ''
Write-Host ("Checks failed: {0}" -f $failures.Count) -ForegroundColor $(if ($failures.Count -eq 0) { 'Green' } else { 'Red' })
Write-Host ("Warnings: {0}" -f $warnings.Count) -ForegroundColor $(if ($warnings.Count -eq 0) { 'Green' } else { 'Yellow' })

if ($failures.Count -gt 0) {
    exit 1
}
exit 0
