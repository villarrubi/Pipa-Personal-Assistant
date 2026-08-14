[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $false)]
    [string]$LocalAddress,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$Port = 18765,

    [switch]$Disable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$transportName = 'PIPA_MOBILE_TRANSPORT'
$bindName = 'PIPA_MOBILE_BIND'
$portName = 'PIPA_MOBILE_PORT'

function Test-PrivateIPv4 {
    param(
        [Parameter(Mandatory)] [string]$Value
    )

    try {
        $address = [System.Net.IPAddress]::Parse($Value.Trim())
    } catch {
        throw 'LocalAddress debe ser una IPv4 literal privada, loopback o link-local.'
    }
    if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'LocalAddress debe ser una IPv4 literal.'
    }
    $bytes = $address.GetAddressBytes()
    $private =
        [System.Net.IPAddress]::IsLoopback($address) -or
        $bytes[0] -eq 10 -or
        ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168) -or
        ($bytes[0] -eq 169 -and $bytes[1] -eq 254)
    if (-not $private) {
        throw 'LocalAddress debe ser una IPv4 privada, loopback o link-local.'
    }
    return $address.IPAddressToString
}

function Test-AssignedIPv4 {
    param(
        [Parameter(Mandatory = $true)] [string]$Value
    )

    if ($Value -eq '127.0.0.1') {
        return $true
    }
    try {
        foreach ($networkInterface in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
            try {
                foreach ($unicast in $networkInterface.GetIPProperties().UnicastAddresses) {
                    if (
                        $unicast.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                        $unicast.Address.IPAddressToString -eq $Value
                    ) {
                        return $true
                    }
                }
            } catch {
                continue
            }
        }
    } catch {
        return $false
    }
    return $false
}

if ($Disable) {
    if ($PSCmdlet.ShouldProcess('Variables de usuario Pipa Mobile TCP v2', 'Desactivar')) {
        [Environment]::SetEnvironmentVariable($transportName, $null, 'User')
        [Environment]::SetEnvironmentVariable($bindName, $null, 'User')
        [Environment]::SetEnvironmentVariable($portName, $null, 'User')
        Remove-Item Env:$transportName -ErrorAction SilentlyContinue
        Remove-Item Env:$bindName -ErrorAction SilentlyContinue
        Remove-Item Env:$portName -ErrorAction SilentlyContinue
        Write-Host 'Transporte movil desactivado para nuevas sesiones del agente.' -ForegroundColor Green
        Write-Host 'La regla de firewall, si existe, se retira aparte con configure_mobile_firewall.ps1 -Remove.'
    }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($LocalAddress)) {
    throw 'LocalAddress es obligatorio al activar el transporte.'
}
$validatedAddress = Test-PrivateIPv4 -Value $LocalAddress
if (-not (Test-AssignedIPv4 -Value $validatedAddress)) {
    throw 'LocalAddress no esta asignada a este PC.'
}

if ($PSCmdlet.ShouldProcess(
        "Configuracion de usuario Pipa Mobile TCP v2 ($validatedAddress`:$Port)",
        'Activar')) {
    [Environment]::SetEnvironmentVariable($transportName, 'tcp-v2', 'User')
    [Environment]::SetEnvironmentVariable($bindName, $validatedAddress, 'User')
    [Environment]::SetEnvironmentVariable($portName, [string]$Port, 'User')
    # User-scope changes do not alter the current PowerShell environment. Keep
    # an immediate hidden-agent restart from inheriting stale transport values.
    $env:PIPA_MOBILE_TRANSPORT = 'tcp-v2'
    $env:PIPA_MOBILE_BIND = $validatedAddress
    $env:PIPA_MOBILE_PORT = [string]$Port
    Write-Host "Transporte movil configurado: tcp-v2 en $validatedAddress`:$Port" -ForegroundColor Green
    Write-Host 'Reinicia el agente para aplicar la configuracion.'
    Write-Host 'Configura el firewall por separado y limitado a red privada:'
    Write-Host ".\scripts\configure_mobile_firewall.ps1 -LocalAddress $validatedAddress -Port $Port -RemoteAddress LocalSubnet -WhatIf"
}
