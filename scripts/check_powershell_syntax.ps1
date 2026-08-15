[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$asciiOnlyFiles = @(
    'windows-agent/check_agent_status.ps1',
    'windows-agent/install_agent_task.ps1',
    'windows-agent/setup_agent.ps1',
    'windows-agent/start_agent_hidden.ps1',
    'windows-agent/uninstall_agent_task.ps1',
    'scripts/pipa_preflight.ps1',
    'scripts/check_agent_startup.ps1',
    'scripts/check_waveshare_pinmap.ps1',
    'scripts/check_firmware_config.ps1',
    'scripts/check_firmware_log_safety.ps1',
    'scripts/check_secure_handshake_contract.ps1',
    'scripts/check_trusted_unlock_safety.ps1',
    'scripts/check_pre_hardware.ps1',
    'scripts/prepare_waveshare.ps1',
    'scripts/flash_waveshare.ps1',
    'scripts/configure_mobile_firewall.ps1',
    'scripts/configure_mobile_transport.ps1',
    'scripts/check_workflow_security.ps1',
    'scripts/check_ci_coverage.ps1',
    'scripts/security_patterns.ps1',
    'scripts/test_security_patterns.ps1'
)

$relativeFiles = @(git -C $repoRoot ls-files -- '*.ps1')
if ($LASTEXITCODE -ne 0 -or $relativeFiles.Count -eq 0) {
    throw 'No se pudo enumerar los scripts PowerShell rastreados por Git.'
}

foreach ($relativeFile in $relativeFiles) {
    $path = Join-Path $repoRoot ($relativeFile -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "No se encuentra el script PowerShell: $relativeFile"
    }

    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $path,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null
    if ($errors.Count -gt 0) {
        $messages = ($errors | ForEach-Object { $_.Message }) -join '; '
        throw "Sintaxis PowerShell invalida en ${relativeFile}: $messages"
    }
}

# Windows PowerShell 5.1 can decode UTF-8 without a BOM as an ANSI code page.
# Keep the compatibility-critical scripts that run setup and repository gates
# ASCII-only so paths, API markers and messages cannot be corrupted.
foreach ($relativeFile in $asciiOnlyFiles) {
    $path = Join-Path $repoRoot ($relativeFile -replace '/', '\')
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if (@($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) {
        throw "El script PowerShell debe ser ASCII para Windows PowerShell 5.1: $relativeFile"
    }
}

Write-Host (
    "Sintaxis PowerShell OK: {0} scripts rastreados; {1} compatibles con ASCII." -f
    $relativeFiles.Count,
    $asciiOnlyFiles.Count
) -ForegroundColor Green
