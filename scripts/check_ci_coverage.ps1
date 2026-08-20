[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workflowPath = Join-Path $repoRoot '.github/workflows/ci.yml'
if (-not (Test-Path -LiteralPath $workflowPath -PathType Leaf)) {
    throw 'No se encuentra el workflow de CI.'
}

$workflow = Get-Content -LiteralPath $workflowPath -Raw
$requiredFragments = @(
    'workflow_dispatch:',
    'concurrency:',
    'cancel-in-progress: true',
    'timeout-minutes: 20',
    'timeout-minutes: 45',
    'timeout-minutes: 30',
    'timeout-minutes: 10',
    'python -m pip install -r windows-agent/requirements-dev.txt',
    'gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e',
    'GITLEAKS_VERSION: 8.30.1',
    'python scripts/check_documentation.py',
    'python scripts/check_python_security.py',
    './scripts/check_workflow_security.ps1',
    './scripts/check_ci_coverage.ps1',
    './scripts/check_powershell_syntax.ps1',
    './scripts/check_agent_startup.ps1',
    './scripts/check_log_safety.ps1',
    './scripts/check_firmware_log_safety.ps1',
    './scripts/check_mobile_ios_package.ps1',
    'python scripts/check_mobile_capability_contract.py',
    'python scripts/check_mobile_catalog_contract.py',
    'python scripts/check_mobile_confirmation_contract.py',
    'python scripts/check_mobile_server_envelope_contract.py',
    'python scripts/check_mobile_safety_contract.py',
    './scripts/check_waveshare_pinmap.ps1',
    './scripts/check_firmware_config.ps1',
    './scripts/check_firmware_flash_safety.ps1',
    './scripts/check_firmware_security_gate.ps1',
    './scripts/check_secure_handshake_contract.ps1',
    './scripts/check_audio_i2s_lab.ps1',
    './scripts/check_firmware_ui_recovery.ps1',
    './scripts/check_secure_audio_contract.ps1',
    './scripts/check_audio_state_machine.ps1',
    './scripts/check_display_text.ps1',
    './scripts/check_trusted_unlock_safety.ps1',
    './scripts/check_pre_hardware.ps1 -SkipResidentAgent',
    'python -B -m unittest discover -s backend/tests -p "test_*.py"',
    'python -B -m unittest discover -s windows-agent/tests -p "test_*.py"',
    './scripts/check_repo_hygiene.ps1',
    './scripts/check_git_history.ps1',
    './scripts/test_security_patterns.ps1',
    'ruff check backend windows-agent scripts',
    'ruff format --check backend windows-agent scripts',
    'python -m compileall -q backend windows-agent scripts',
    'swift test --package-path mobile-ios',
    'xcodebuild -project mobile-ios/PipaMobileApp/PipaMobile.xcodeproj',
    'cmake -S trusted-unlock -B trusted-unlock/build-ci -A x64',
    'cmake --build trusted-unlock/build-ci --config Release',
    '.\trusted-unlock\build-ci\Release\PipaProviderTest.exe',
    'run_pio_with_retry waveshare-185c',
    'run_pio_with_retry waveshare-185c-v1',
    'run_pio_with_retry secure-session-v2',
    'run_pio_with_retry secure-session-vector',
    'firmware/src/pipa_voice_activity.cpp',
    'run_pio_with_retry voice-v2',
    'run_pio_with_retry voice-v2-handsfree',
    'run_pio_with_retry audio-i2s-lab',
    'gh-action-pip-audit',
    'inputs: windows-agent/requirements-dev.txt'
)

$missing = @(
    $requiredFragments | Where-Object {
        $workflow.IndexOf($_, [System.StringComparison]::Ordinal) -lt 0
    }
)
if ($missing.Count -gt 0) {
    throw "El workflow no contiene las compuertas requeridas: $($missing -join ', ')"
}

Write-Host ("Cobertura CI OK: {0} compuertas y tareas requeridas presentes." -f $requiredFragments.Count) -ForegroundColor Green
