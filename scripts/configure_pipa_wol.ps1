[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$Ssid,
    [Security.SecureString]$WifiPassword,
    [string]$MacAddress,
    [switch]$OpenNetwork
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$localConfigPath = Join-Path $repoRoot 'firmware/include/pipa_device_config.local.h'

function Get-DetectedEthernetMac {
    $candidates = @()
    try {
        $candidates = @(
            Get-NetAdapter -Physical -ErrorAction Stop |
                Where-Object {
                    $_.Status -eq 'Up' -and
                    [int]$_.NdisPhysicalMedium -eq 14 -and
                    -not [string]::IsNullOrWhiteSpace([string]$_.MacAddress)
                }
        )
    } catch {
        $candidates = @(
            Get-CimInstance Win32_NetworkAdapter -ErrorAction Stop |
                Where-Object {
                    $_.NetEnabled -eq $true -and
                    [int]$_.AdapterTypeID -eq 0 -and
                    -not [string]::IsNullOrWhiteSpace([string]$_.MACAddress)
                }
        )
    }
    if ($candidates.Count -ne 1) {
        throw 'No se pudo elegir una unica Ethernet activa; usa -MacAddress AA:BB:CC:DD:EE:FF.'
    }
    $candidate = $candidates[0]
    if ($null -ne $candidate.PSObject.Properties['MacAddress']) {
        return [string]$candidate.MacAddress
    }
    return [string]$candidate.MACAddress
}

function Get-NormalizedMac {
    param([Parameter(Mandatory)] [string]$Value)

    $normalized = $Value.Trim().Replace('-', ':').ToUpperInvariant()
    if ($normalized -notmatch '^[0-9A-F]{2}(:[0-9A-F]{2}){5}$') {
        throw 'La MAC Ethernet no tiene el formato AA:BB:CC:DD:EE:FF.'
    }
    $bytes = @($normalized.Split(':') | ForEach-Object { [Convert]::ToByte($_, 16) })
    if (($bytes[0] -band 1) -ne 0 -or @($bytes | Where-Object { $_ -ne 0 }).Count -eq 0 -or
        @($bytes | Where-Object { $_ -ne 255 }).Count -eq 0) {
        throw 'La MAC Ethernet debe ser una direccion unicast concreta.'
    }
    return $normalized
}

function ConvertTo-FirmwareCString {
    param(
        [Parameter(Mandatory)] [string]$Value,
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [int]$MaximumBytes
    )

    if ($Value.IndexOf([char]0) -ge 0 -or
        @($Value.ToCharArray() | Where-Object { [int]$_ -lt 32 -or [int]$_ -eq 127 }).Count -gt 0) {
        throw "$Name contiene caracteres de control no admitidos."
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    if ($bytes.Count -eq 0 -or $bytes.Count -gt $MaximumBytes) {
        throw "$Name debe ocupar entre 1 y $MaximumBytes bytes UTF-8."
    }
    $builder = [Text.StringBuilder]::new()
    foreach ($byte in $bytes) {
        if ($byte -eq 34) {
            [void]$builder.Append('\"')
        } elseif ($byte -eq 92) {
            [void]$builder.Append('\\')
        } elseif ($byte -ge 32 -and $byte -le 126) {
            [void]$builder.Append([char]$byte)
        } else {
            [void]$builder.Append('\' + [Convert]::ToString($byte, 8).PadLeft(3, '0'))
        }
    }
    return $builder.ToString()
}

function Set-StringDefine {
    param(
        [Parameter(Mandatory)] [string]$Content,
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$EscapedValue
    )

    $pattern = '(?m)^(?<prefix>\s*#define\s+' + [regex]::Escape($Name) +
        '\s+)"(?:\\.|[^"\\])*"(?<suffix>\s*)$'
    $matches = [regex]::Matches($Content, $pattern)
    if ($matches.Count -ne 1) {
        throw "La configuracion local debe contener exactamente una definicion $Name."
    }
    return [regex]::Replace(
        $Content,
        $pattern,
        { param($match) $match.Groups['prefix'].Value + '"' + $EscapedValue + '"' + $match.Groups['suffix'].Value }
    )
}

if (-not (Test-Path -LiteralPath $localConfigPath -PathType Leaf)) {
    throw 'Falta pipa_device_config.local.h; provisiona primero la identidad segura de Pipa.'
}
if ([string]::IsNullOrWhiteSpace($Ssid)) {
    $Ssid = Read-Host 'Nombre de la red Wi-Fi de 2.4 GHz (SSID)'
}
if ([string]::IsNullOrWhiteSpace($MacAddress)) {
    $MacAddress = Get-DetectedEthernetMac
}
$normalizedMac = Get-NormalizedMac -Value $MacAddress
$escapedSsid = ConvertTo-FirmwareCString -Value $Ssid -Name 'El SSID' -MaximumBytes 32

if ($OpenNetwork -and $null -ne $WifiPassword) {
    throw 'No combines -OpenNetwork con -WifiPassword.'
}
if (-not $OpenNetwork -and $null -eq $WifiPassword) {
    $WifiPassword = Read-Host 'Clave Wi-Fi (no se mostrara)' -AsSecureString
}

$plainPassword = ''
$passwordPointer = [IntPtr]::Zero
try {
    if (-not $OpenNetwork) {
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($WifiPassword)
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        $passwordBytes = [Text.Encoding]::UTF8.GetByteCount($plainPassword)
        $isPassphrase = $passwordBytes -ge 8 -and $passwordBytes -le 63
        $isRawPsk = $passwordBytes -eq 64 -and $plainPassword -match '^[0-9A-Fa-f]{64}$'
        if (-not $isPassphrase -and -not $isRawPsk) {
            throw 'La clave Wi-Fi debe tener 8-63 bytes o ser una PSK hexadecimal de 64 caracteres.'
        }
    }
    $escapedPassword = if ($OpenNetwork) {
        ''
    } else {
        ConvertTo-FirmwareCString -Value $plainPassword -Name 'La clave Wi-Fi' -MaximumBytes 64
    }

    $content = Get-Content -LiteralPath $localConfigPath -Raw
    $updated = Set-StringDefine -Content $content -Name 'PIPA_WIFI_SSID' -EscapedValue $escapedSsid
    $updated = Set-StringDefine -Content $updated -Name 'PIPA_WIFI_PASSWORD' -EscapedValue $escapedPassword
    $updated = Set-StringDefine -Content $updated -Name 'PIPA_PC_MAC' -EscapedValue $normalizedMac

    if ($PSCmdlet.ShouldProcess($localConfigPath, 'configurar Wi-Fi y Wake-on-LAN')) {
        $temporaryPath = $localConfigPath + '.tmp'
        try {
            [IO.File]::WriteAllText($temporaryPath, $updated, [Text.UTF8Encoding]::new($false))
            Move-Item -LiteralPath $temporaryPath -Destination $localConfigPath -Force
        } finally {
            if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
                Remove-Item -LiteralPath $temporaryPath -Force
            }
        }
        Write-Host 'Wi-Fi local configurada; la clave no se ha mostrado ni versionado.' -ForegroundColor Green
        Write-Host ("MAC Ethernet para Wake-on-LAN: {0}" -f $normalizedMac) -ForegroundColor Green
        Write-Host 'Siguiente paso: recompilar y cargar voice-v2-handsfree.' -ForegroundColor Cyan
    }
} finally {
    $plainPassword = $null
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
}
