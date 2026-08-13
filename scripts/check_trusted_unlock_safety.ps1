[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$providerPath = Join-Path $repoRoot 'trusted-unlock/src/PipaCredential.cpp'
$credentialProviderPath = Join-Path $repoRoot 'trusted-unlock/src/CredentialProvider.cpp'
$brokerPath = Join-Path $repoRoot 'windows-agent/trusted_unlock_broker.py'
$brokerTestsPath = Join-Path $repoRoot 'windows-agent/tests/test_trusted_unlock_broker.py'

foreach ($path in @($providerPath, $credentialProviderPath, $brokerPath, $brokerTestsPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta el archivo de seguridad Trusted Unlock: $path"
    }
}

$provider = Get-Content -LiteralPath $providerPath -Raw
$credentialProvider = Get-Content -LiteralPath $credentialProviderPath -Raw
$broker = Get-Content -LiteralPath $brokerPath -Raw
$brokerTests = Get-Content -LiteralPath $brokerTestsPath -Raw

foreach ($marker in @(
        'constexpr bool kTrustedUnlockEnabled = false;',
        'static_assert(',
        '!kTrustedUnlockEnabled',
        'CPGSR_NO_CREDENTIAL_NOT_FINISHED',
        '*pcpgsr = CPGSR_NO_CREDENTIAL_NOT_FINISHED',
        'ZeroMemory(',
        'pcpcs'
    )) {
    if ($provider.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El Credential Provider no conserva el bloqueo requerido: $marker"
    }
}

if ($credentialProvider.IndexOf('return E_NOTIMPL;', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'CredentialProvider.cpp no rechaza serializaciones externas.'
}
if ($broker.IndexOf('UNLOCK_ENABLED: Final[bool] = False', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El broker no declara Trusted Unlock desactivado.'
}
if ($broker.IndexOf('unsupported broker command', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El broker no conserva una lista cerrada de comandos.'
}
if ($brokerTests.IndexOf('assertFalse(response["result"]["unlock_enabled"])', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'Las pruebas del broker no comprueban unlock_enabled=false.'
}

Write-Host 'Trusted Unlock seguro: provider, broker y pruebas mantienen el desbloqueo inerte.' -ForegroundColor Green
