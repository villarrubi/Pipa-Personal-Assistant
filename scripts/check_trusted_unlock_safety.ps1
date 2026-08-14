[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$providerPath = Join-Path $repoRoot 'trusted-unlock/src/PipaCredential.cpp'
$credentialProviderPath = Join-Path $repoRoot 'trusted-unlock/src/CredentialProvider.cpp'
$brokerPath = Join-Path $repoRoot 'windows-agent/trusted_unlock_broker.py'
$brokerClientPath = Join-Path $repoRoot 'windows-agent/trusted_unlock_broker_client.py'
$brokerTestsPath = Join-Path $repoRoot 'windows-agent/tests/test_trusted_unlock_broker.py'
$uninstallPath = Join-Path $repoRoot 'trusted-unlock/uninstall.ps1'

foreach ($path in @($providerPath, $credentialProviderPath, $brokerPath, $brokerClientPath, $brokerTestsPath, $uninstallPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta el archivo de seguridad Trusted Unlock: $path"
    }
}

$provider = Get-Content -LiteralPath $providerPath -Raw
$credentialProvider = Get-Content -LiteralPath $credentialProviderPath -Raw
$broker = Get-Content -LiteralPath $brokerPath -Raw
$brokerClient = Get-Content -LiteralPath $brokerClientPath -Raw
$brokerTests = Get-Content -LiteralPath $brokerTestsPath -Raw
$uninstall = Get-Content -LiteralPath $uninstallPath -Raw
$installer = Get-Content -LiteralPath (Join-Path $repoRoot 'trusted-unlock/install.ps1') -Raw

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

foreach ($marker in @(
        'function Assert-NoReparsePoint',
        'Assert-NoReparsePoint -Path $source',
        'Assert-NoReparsePoint -Path $InstalledDllPath',
        '$installedSha256 = (Get-FileHash -LiteralPath $InstalledDllPath -Algorithm SHA256).Hash.ToUpperInvariant()',
        'La DLL instalada no coincide con el hash calculado antes de copiarla.'
    )) {
    if ($installer.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El instalador no conserva la defensa de ruta/hash requerida: $marker"
    }
}
foreach ($marker in @(
        'function Assert-NoReparsePoint',
        'Assert-NoReparsePoint -Path $InstalledDllPath',
        'no se eliminara nada'
    )) {
    if ($uninstall.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El rollback no conserva la defensa de ruta requerida: $marker"
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

foreach ($marker in @(
    'PIPE_NAME = r"\\.\pipe\PipaTrustedUnlock"',
    'PIPE_REJECT_REMOTE_CLIENTS_FLAG =',
    'FILE_FLAG_FIRST_PIPE_INSTANCE =',
    'def _security_attributes',
    'win32security.OpenProcessToken',
    'GetTokenInformation',
    'AddAccessAllowedAce',
    'LookupAccountName(None, "SYSTEM")',
    'CreateNamedPipe(',
    'PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE',
    'PIPE_REJECT_REMOTE_CLIENTS',
    'MAX_MESSAGE_BYTES + 1'
)) {
    if ($broker.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El broker no conserva el invariante IPC requerido: $marker"
    }
}
if ($broker -match '(?i)Everyone|Authenticated Users|WorldSid|AF_INET|http\.server|socket\.socket') {
    throw 'El broker no puede ampliar la ACL ni anadir un transporte de red.'
}
foreach ($marker in @(
    'object_pairs_hook=_reject_duplicate_fields',
    'def _decode_response',
    'successful broker response has invalid fields',
    'broker error is invalid'
)) {
    if ($brokerClient.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El cliente del broker no conserva la validacion estricta de respuestas: $marker"
    }
}
if ($brokerClient.IndexOf('if pipe_name != PIPE_NAME:', [System.StringComparison]::Ordinal) -lt 0 -or
    $brokerTests.IndexOf('rejects_non_local_pipe_names', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El cliente del broker no conserva la validacion de pipe fijo/local.'
}
if ($brokerTests.IndexOf('16 * 1024 + 1', [System.StringComparison]::Ordinal) -lt 0 -or
    $brokerTests.IndexOf('ticket_replay', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'Las pruebas del broker no cubren limites y anti-replay.'
}
foreach ($marker in @('Test-ExactValueNames', 'GetValueNames()', 'no se elimin')) {
    if ($uninstall.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El rollback no verifica la propiedad exacta de las claves: $marker"
    }
}

Write-Host 'Trusted Unlock seguro: provider, broker y pruebas mantienen el desbloqueo inerte.' -ForegroundColor Green
