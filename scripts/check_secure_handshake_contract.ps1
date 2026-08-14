[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cppPath = Join-Path $repoRoot 'firmware/src/pipa_secure_handshake.cpp'
$headerPath = Join-Path $repoRoot 'firmware/src/pipa_secure_handshake.h'
$pythonPath = Join-Path $repoRoot 'windows-agent/secure_session.py'

foreach ($path in @($cppPath, $headerPath, $pythonPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta una implementacion del contrato de handshake: $path"
    }
}

$cpp = Get-Content -LiteralPath $cppPath -Raw
$header = Get-Content -LiteralPath $headerPath -Raw
$python = Get-Content -LiteralPath $pythonPath -Raw

# Keep this list duplicated at the audit boundary. If either implementation
# adds a field, this gate forces the protocol change to be reviewed in both
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
        'def _transcript_hash'
    )) {
    if ($cpp.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0 -and
        $header.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0 -and
        $python.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
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

Write-Host 'Contrato de handshake seguro OK: C++ y Python mantienen el ServerHello estricto y autenticado.' -ForegroundColor Green
Exit 0
