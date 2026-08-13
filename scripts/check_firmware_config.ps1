[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$trackedConfig = Join-Path $repoRoot 'firmware/include/pipa_device_config.h'
$exampleConfig = Join-Path $repoRoot 'firmware/include/pipa_device_config.example.h'
$localConfig = Join-Path $repoRoot 'firmware/include/pipa_device_config.local.h'
$textPolicy = Join-Path $repoRoot 'firmware/src/pipa_text_policy.h'
$identitySource = Join-Path $repoRoot 'firmware/src/device_identity.cpp'
$configPath = if (Test-Path -LiteralPath $localConfig -PathType Leaf) {
    $localConfig
} else {
    $trackedConfig
}

if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw 'No existe la configuracion base del firmware.'
}
if (-not (Test-Path -LiteralPath $exampleConfig -PathType Leaf)) {
    throw 'No existe la plantilla de configuracion del firmware.'
}
if (-not (Test-Path -LiteralPath $textPolicy -PathType Leaf)) {
    throw 'Falta la politica de texto seguro del firmware.'
}
if (-not (Test-Path -LiteralPath $identitySource -PathType Leaf)) {
    throw 'Falta la implementacion de identidad del firmware.'
}
$identityContent = Get-Content -LiteralPath $identitySource -Raw
foreach ($marker in @('preferences_.end()', 'ready_ = false', 'memset(private_key_, 0, sizeof(private_key_))')) {
    if ($identityContent.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "La identidad del firmware no contiene el control de ciclo de vida requerido: $marker."
    }
}
$textPolicyContent = Get-Content -LiteralPath $textPolicy -Raw
foreach ($marker in @('isSafeDisplayText', 'malformed UTF-8', '0x202A', '0xFEFF')) {
    if ($textPolicyContent.IndexOf($marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw "La politica de texto del firmware no contiene el control requerido: $marker."
    }
}
foreach ($protocolSource in @('firmware/src/pipa_protocol.cpp', 'firmware/src/pipa_secure_protocol.cpp')) {
    $protocolPath = Join-Path $repoRoot $protocolSource
    if (-not (Test-Path -LiteralPath $protocolPath -PathType Leaf)) {
        throw "Falta el origen de protocolo del firmware: $protocolSource."
    }
    $protocolContent = Get-Content -LiteralPath $protocolPath -Raw
    if ($protocolContent.IndexOf('pipa_text_policy.h', [System.StringComparison]::Ordinal) -lt 0 -or
        $protocolContent.IndexOf('isSafeDisplayText', [System.StringComparison]::Ordinal) -lt 0) {
        throw "El protocolo $protocolSource no aplica la politica de texto seguro."
    }
}

$config = Get-Content -LiteralPath $configPath -Raw
$exampleContent = Get-Content -LiteralPath $exampleConfig -Raw

$safeTemplateDefines = @{
    'PIPA_WIFI_SSID' = '""'
    'PIPA_WIFI_PASSWORD' = '""'
    'PIPA_PC_MAC' = '"00:00:00:00:00:00"'
    'PIPA_SECURE_SERVER_PUBLIC_KEY' = '""'
    'PIPA_SECURE_SESSION_ENABLED' = '0'
}
foreach ($entry in $safeTemplateDefines.GetEnumerator()) {
    $templatePattern = '(?m)^\s*#define\s+' + [regex]::Escape($entry.Key) + '\s+' + [regex]::Escape($entry.Value) + '\s*$'
    if (-not [regex]::IsMatch($exampleContent, $templatePattern)) {
        throw "La plantilla publica no mantiene el valor seguro esperado para $($entry.Key)."
    }
}

function Get-StringDefine {
    param(
        [Parameter(Mandatory)] [string]$Name
    )

    $pattern = '(?m)^\s*#define\s+' + [regex]::Escape($Name) + '\s+"(?<value>[^"]*)"\s*$'
    $match = [regex]::Match($config, $pattern)
    if (-not $match.Success) {
        throw "Falta la definicion $Name en la configuracion del firmware."
    }
    return $match.Groups['value'].Value
}

function Get-IntegerDefine {
    param(
        [Parameter(Mandatory)] [string]$Name
    )

    $pattern = '(?m)^\s*#define\s+' + [regex]::Escape($Name) + '\s+(?<value>[0-9]+)\s*$'
    $match = [regex]::Match($config, $pattern)
    if (-not $match.Success) {
        throw "Falta la definicion numerica $Name en la configuracion del firmware."
    }
    return [int]$match.Groups['value'].Value
}

function Assert-BoundedText {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$Value,
        [Parameter(Mandatory)] [int]$Maximum
    )

    if ($Value.Length -eq 0 -or $Value.Length -gt $Maximum -or
        $Value.IndexOf([char]0) -ge 0 -or
        @($Value.ToCharArray() | Where-Object { [int]$_ -lt 32 -or [int]$_ -eq 127 }).Count -gt 0) {
        throw "$Name no tiene un valor de texto acotado."
    }
}

$ssid = Get-StringDefine -Name 'PIPA_WIFI_SSID'
$password = Get-StringDefine -Name 'PIPA_WIFI_PASSWORD'
$pcMac = Get-StringDefine -Name 'PIPA_PC_MAC'
$deviceId = Get-StringDefine -Name 'PIPA_DEVICE_ID'
$firmwareVersion = Get-StringDefine -Name 'PIPA_FIRMWARE_VERSION'
$serverId = Get-StringDefine -Name 'PIPA_SECURE_SERVER_ID'
$serverKey = Get-StringDefine -Name 'PIPA_SECURE_SERVER_PUBLIC_KEY'
$secureEnabled = Get-IntegerDefine -Name 'PIPA_SECURE_SESSION_ENABLED'
$boardRevision = Get-IntegerDefine -Name 'PIPA_BOARD_REVISION'

if ($ssid.Length -gt 64 -or $password.Length -gt 128) {
    throw 'La configuracion Wi-Fi supera los limites admitidos.'
}
if ($pcMac -notmatch '^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$') {
    throw 'PIPA_PC_MAC no tiene formato MAC.'
}
if ($deviceId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
    throw 'PIPA_DEVICE_ID no tiene un identificador valido.'
}
Assert-BoundedText -Name 'PIPA_FIRMWARE_VERSION' -Value $firmwareVersion -Maximum 32
if ($secureEnabled -notin @(0, 1)) {
    throw 'PIPA_SECURE_SESSION_ENABLED solo puede ser 0 o 1.'
}
if ($boardRevision -notin @(1, 2)) {
    throw 'PIPA_BOARD_REVISION solo puede ser 1 o 2.'
}

if ($secureEnabled -eq 1) {
    if ($serverId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$') {
        throw 'PIPA_SECURE_SERVER_ID no tiene un identificador valido.'
    }
    if ($serverKey -notmatch '^[A-Za-z0-9_-]{43}$') {
        throw 'La clave publica v2 no tiene la longitud base64url esperada.'
    }
    $standardKey = $serverKey.Replace('-', '+').Replace('_', '/')
    $padding = '=' * ((4 - ($standardKey.Length % 4)) % 4)
    try {
        $decodedKey = [Convert]::FromBase64String($standardKey + $padding)
    } catch {
        throw 'La clave publica v2 no es base64 valida.'
    }
    if ($decodedKey.Length -ne 32) {
        throw 'La clave publica v2 no contiene 32 bytes.'
    }
    $canonicalKey = [Convert]::ToBase64String($decodedKey).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    if ($canonicalKey -cne $serverKey) {
        throw 'La clave publica v2 no usa una codificacion base64url canonica.'
    }
} elseif ($serverKey.Length -ne 0) {
    throw 'La clave publica v2 debe estar vacia mientras la sesion segura esta desactivada.'
}

if (Test-Path -LiteralPath $localConfig -PathType Leaf) {
    git -C $repoRoot check-ignore --quiet -- 'firmware/include/pipa_device_config.local.h'
    if ($LASTEXITCODE -ne 0) {
        throw 'La configuracion local del firmware no esta cubierta por .gitignore.'
    }
    Write-Host 'Configuracion firmware local valida; valores sensibles no mostrados.' -ForegroundColor Green
} else {
    Write-Host 'Configuracion firmware rastreada segura; no hay provisioning local.' -ForegroundColor Green
}
