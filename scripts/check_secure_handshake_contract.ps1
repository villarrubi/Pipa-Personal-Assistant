[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cppPath = Join-Path $repoRoot 'firmware/src/pipa_secure_handshake.cpp'
$headerPath = Join-Path $repoRoot 'firmware/src/pipa_secure_handshake.h'
$pythonPath = Join-Path $repoRoot 'windows-agent/secure_session.py'
$swiftPath = Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileProtocol.swift'

foreach ($path in @($cppPath, $headerPath, $pythonPath, $swiftPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta una implementacion del contrato de handshake: $path"
    }
}

$cpp = Get-Content -LiteralPath $cppPath -Raw
$header = Get-Content -LiteralPath $headerPath -Raw
$python = Get-Content -LiteralPath $pythonPath -Raw
$swift = Get-Content -LiteralPath $swiftPath -Raw

# Keep this list duplicated at the audit boundary. If either implementation
# adds a field, this gate forces the protocol change to be reviewed in every
# languages instead of silently widening the wire format.
$serverHelloFields = @(
    'client_ephemeral_public_key',
    'client_id',
    'client_nonce',
    'protocol_version',
    'server_ephemeral_public_key',
    'server_id',
    'server_nonce',
    'session_id',
    'signature'
)

foreach ($field in $serverHelloFields) {
    if ($cpp.IndexOf(('"{0}"' -f $field), [System.StringComparison]::Ordinal) -lt 0) {
        throw "El handshake C++ no contiene el campo ServerHello requerido: $field"
    }
    if ($python.IndexOf(('"{0}"' -f $field), [System.StringComparison]::Ordinal) -lt 0) {
        throw "El handshake Python no serializa el campo ServerHello requerido: $field"
    }
    if ($swift.IndexOf(('"{0}"' -f $field), [System.StringComparison]::Ordinal) -lt 0) {
        throw "El handshake Swift no valida el campo ServerHello requerido: $field"
    }
}

foreach ($marker in @(
        'hasExactServerHelloFields',
        'return field_count == 9',
        'server_hello.isNull()',
        '!server_hello["protocol_version"].is<int>()',
        'Ed25519::verify',
        'Curve25519::eval',
        'session.beginFromSharedSecret',
        'class ServerHello',
        'def complete_client_handshake',
        'def _transcript_hash',
        'let expectedFields: Set<String> = [',
        'Set(serverHello.keys) == expectedFields'
    )) {
    if ($cpp.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0 -and
        $header.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0 -and
        $python.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0 -and
        $swift.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "Falta una barrera del handshake autenticado: $marker"
    }
}

if ($cpp -notmatch '(?s)hasExactServerHelloFields\(JsonObjectConst object\).*?return field_count == 9;') {
    throw 'El parser C++ no exige exactamente los nueve campos de ServerHello.'
}
if ($cpp -notmatch '(?s)acceptServerHello\(.*?hasExactServerHelloFields\(server_hello\)') {
    throw 'acceptServerHello no aplica la validacion estricta de campos.'
}
if ($python -notmatch '(?s)def complete_client_handshake\(.*?server_public_key\.verify') {
    throw 'El cliente Python no verifica la firma de ServerHello.'
}
if ($swift -notmatch '(?s)let expectedFields: Set<String> = \[.*?\]\s*guard Set\(serverHello\.keys\) == expectedFields') {
    throw 'El cliente Swift no exige el conjunto exacto de campos de ServerHello.'
}
$swiftExpectedStart = $swift.IndexOf('let expectedFields: Set<String> = [', [System.StringComparison]::Ordinal)
$swiftExpectedEnd = $swift.IndexOf(']', $swiftExpectedStart, [System.StringComparison]::Ordinal)
if ($swiftExpectedStart -lt 0 -or $swiftExpectedEnd -lt 0) {
    throw 'No se pudo analizar la allowlist Swift de ServerHello.'
}
$swiftExpectedBlock = $swift.Substring($swiftExpectedStart, $swiftExpectedEnd - $swiftExpectedStart)
$swiftExpectedFields = @(
    [regex]::Matches($swiftExpectedBlock, '"([A-Za-z0-9_-]+)"') |
        ForEach-Object { $_.Groups[1].Value }
)
$swiftMissingFields = @($serverHelloFields | Where-Object { $_ -notin $swiftExpectedFields })
$swiftExtraFields = @($swiftExpectedFields | Where-Object { $_ -notin $serverHelloFields })
if ($swiftExpectedFields.Count -ne $serverHelloFields.Count -or
    $swiftMissingFields.Count -gt 0 -or $swiftExtraFields.Count -gt 0) {
    throw 'La allowlist Swift de ServerHello no coincide exactamente con los nueve campos requeridos.'
}

Write-Host 'Contrato de handshake seguro OK: C++, Python y Swift mantienen el ServerHello estricto y autenticado.' -ForegroundColor Green
Exit 0
