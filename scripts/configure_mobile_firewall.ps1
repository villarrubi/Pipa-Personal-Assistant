[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $false)]
    [string]$LocalAddress,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$Port = 18765,

    [Parameter(Mandatory = $false)]
    [string]$RemoteAddress = 'LocalSubnet',

    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ruleName = 'Pipa Mobile TCP v2'

function Test-PrivateIPv4 {
    param(
        [Parameter(Mandatory)] [string]$Value,
        [Parameter(Mandatory)] [string]$FieldName
    )

    try {
        $address = [System.Net.IPAddress]::Parse($Value.Trim())
    } catch {
        throw "$FieldName debe ser una IPv4 literal privada, loopback o link-local."
    }
    if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw "$FieldName debe ser una IPv4 literal."
    }
    $bytes = $address.GetAddressBytes()
    $private =
        [System.Net.IPAddress]::IsLoopback($address) -or
        $bytes[0] -eq 10 -or
        ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168) -or
        ($bytes[0] -eq 169 -and $bytes[1] -eq 254)
    if (-not $private) {
        throw "$FieldName debe ser una IPv4 privada, loopback o link-local."
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

function Test-RemoteAddress {
    param(
        [Parameter(Mandatory)] [string]$Value
    )

    if ($Value -eq 'LocalSubnet') {
        return $Value
    }
    return Test-PrivateIPv4 -Value $Value -FieldName 'RemoteAddress'
}

if (-not $Remove) {
    if ([string]::IsNullOrWhiteSpace($LocalAddress)) {
        throw 'LocalAddress es obligatorio al crear la regla.'
    }
    $validatedLocalAddress = Test-PrivateIPv4 -Value $LocalAddress -FieldName 'LocalAddress'
    if (-not (Test-AssignedIPv4 -Value $validatedLocalAddress)) {
        throw 'LocalAddress no esta asignada a este PC.'
    }
    $validatedRemoteAddress = Test-RemoteAddress -Value $RemoteAddress
}

if ($Remove) {
    if ($PSCmdlet.ShouldProcess($ruleName, 'Eliminar regla de firewall de Pipa')) {
        Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        Write-Host "Regla eliminada: $ruleName" -ForegroundColor Green
    }
    exit 0
}

$description = 'Pipa TCP v2: solo perfil Private y origen privado explicito.'
if ($PSCmdlet.ShouldProcess(
        "$ruleName ($validatedLocalAddress`:$Port)",
        'Crear regla de entrada limitada')) {
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Description $description `
        -Direction Inbound `
        -Action Allow `
        -Enabled True `
        -Profile Private `
        -Protocol TCP `
        -LocalAddress $validatedLocalAddress `
        -LocalPort $Port `
        -RemoteAddress $validatedRemoteAddress `
        -EdgeTraversalPolicy Block `
        -ErrorAction Stop | Out-Null
    Write-Host "Regla creada: $ruleName ($validatedLocalAddress`:$Port)" -ForegroundColor Green
}
