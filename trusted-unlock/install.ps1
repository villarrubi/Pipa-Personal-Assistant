[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [string] $DllPath,

    [Parameter()]
    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string] $ExpectedSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProviderGuid = '{7D886843-37F4-4C64-A45A-8550F112E57A}'
$ProviderName = 'Pipa Trusted Unlock'
$InstallRoot = Join-Path ${env:ProgramFiles} 'Pipa\TrustedUnlock'
$InstalledDllPath = Join-Path $InstallRoot 'PipaTrustedUnlock.dll'
$ProviderRegistryPath = "SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$ProviderGuid"
$ClsidRegistryPath = "SOFTWARE\Classes\CLSID\$ProviderGuid"
$InprocRegistryPath = "$ClsidRegistryPath\InprocServer32"

if ([string]::IsNullOrWhiteSpace($DllPath)) {
    $DllPath = Join-Path $PSScriptRoot 'build\Release\PipaTrustedUnlock.dll'
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-X64PeFile {
    param([Parameter(Mandatory)][string] $Path)

    $bytes = [System.IO.File]::ReadAllBytes($Path)

    if ($bytes.Length -lt 0x40 -or $bytes[0] -ne 0x4D -or $bytes[1] -ne 0x5A) {
        throw "El archivo no parece ser un ejecutable PE valido: $Path"
    }

    $peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
    if ($peOffset -lt 0 -or ($peOffset + 6) -gt $bytes.Length) {
        throw "El encabezado PE no es valido: $Path"
    }

    $signature = [BitConverter]::ToUInt32($bytes, $peOffset)
    $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)

    if ($signature -ne 0x00004550 -or $machine -ne 0x8664) {
        throw "La DLL debe ser x64 (PE machine 0x8664): $Path"
    }
}

function Assert-NoReparsePoint {
    param([Parameter(Mandatory)][string] $Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "La ruta no puede ser un enlace ni un reparse point: $Path"
    }
}

if (-not (Test-Administrator)) {
    throw 'Ejecuta install.ps1 en PowerShell como administrador.'
}

if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    throw 'Este instalador requiere Windows x64 y PowerShell x64.'
}

$source = (Resolve-Path -LiteralPath $DllPath -ErrorAction Stop).Path
$sourceItem = Get-Item -LiteralPath $source
if (-not $sourceItem.PSIsContainer -and $sourceItem.Extension -ieq '.dll') {
    Assert-NoReparsePoint -Path $source
    Test-X64PeFile -Path $source
} else {
    throw "La ruta de la DLL no es valida: $source"
}

$pipaInstallParent = Join-Path ${env:ProgramFiles} 'Pipa'
Assert-NoReparsePoint -Path $pipaInstallParent
Assert-NoReparsePoint -Path $InstallRoot
Assert-NoReparsePoint -Path $InstalledDllPath

$actualSha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToUpperInvariant()
Write-Host "SHA-256:      $actualSha256"
if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and
    $actualSha256 -ne $ExpectedSha256.ToUpperInvariant()) {
    throw "El SHA-256 de la DLL no coincide con ExpectedSha256."
}

if (Test-Path -LiteralPath $InstalledDllPath) {
    throw "Ya existe una instalacion en '$InstalledDllPath'. Ejecuta uninstall.ps1 antes de reinstalar."
}

$registryBase = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
    [Microsoft.Win32.RegistryHive]::LocalMachine,
    [Microsoft.Win32.RegistryView]::Registry64
)
$createdProviderKey = $false
$createdClsidKey = $false
$createdInprocKey = $false
$copiedDll = $false
$registrationApplied = $false

try {
    $existingProvider = $registryBase.OpenSubKey($ProviderRegistryPath, $false)
    $existingClsid = $registryBase.OpenSubKey($ClsidRegistryPath, $false)

    try {
        if ($null -ne $existingProvider -or $null -ne $existingClsid) {
            throw "Ya existe una clave de registro para $ProviderGuid. No se sobrescribira ninguna clave."
        }
    } finally {
        if ($null -ne $existingProvider) { $existingProvider.Dispose() }
        if ($null -ne $existingClsid) { $existingClsid.Dispose() }
    }

    Write-Host "Origen:       $source"
    Write-Host "Destino DLL:  $InstalledDllPath"
    Write-Host "Registro:     HKLM\$ProviderRegistryPath"
    Write-Host "Registro COM: HKLM\$InprocRegistryPath"

    $copyApproved = $PSCmdlet.ShouldProcess($InstalledDllPath, 'Copiar DLL x64')
    if ($copyApproved) {
        New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
        Assert-NoReparsePoint -Path $pipaInstallParent
        Assert-NoReparsePoint -Path $InstallRoot
        Copy-Item -LiteralPath $source -Destination $InstalledDllPath -Force:$false
        $installedSha256 = (Get-FileHash -LiteralPath $InstalledDllPath -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($installedSha256 -ne $actualSha256) {
            throw 'La DLL instalada no coincide con el hash calculado antes de copiarla.'
        }
        $copiedDll = $true
    }

    if ($copyApproved -and $PSCmdlet.ShouldProcess("HKLM:\$ProviderRegistryPath y HKLM:\$ClsidRegistryPath", 'Registrar Credential Provider adicional')) {
        $providerKey = $registryBase.CreateSubKey($ProviderRegistryPath)
        $createdProviderKey = $true
        try {
            $providerKey.SetValue('', $ProviderName, [Microsoft.Win32.RegistryValueKind]::String)
        } finally {
            $providerKey.Dispose()
        }

        $clsidKey = $registryBase.CreateSubKey($ClsidRegistryPath)
        $createdClsidKey = $true
        try {
            $clsidKey.SetValue('', "$ProviderName Credential Provider", [Microsoft.Win32.RegistryValueKind]::String)
        } finally {
            $clsidKey.Dispose()
        }

        $inprocKey = $registryBase.CreateSubKey($InprocRegistryPath)
        $createdInprocKey = $true
        try {
            $inprocKey.SetValue('', $InstalledDllPath, [Microsoft.Win32.RegistryValueKind]::String)
            $inprocKey.SetValue('ThreadingModel', 'Apartment', [Microsoft.Win32.RegistryValueKind]::String)
        } finally {
            $inprocKey.Dispose()
        }
        $registrationApplied = $true
    }

    if (-not $WhatIfPreference -and (-not $copyApproved -or -not $registrationApplied)) {
        throw 'La instalación no se confirmó por completo; se revertirán los cambios parciales.'
    }

    if (-not $WhatIfPreference) {
        Write-Host 'Instalacion preparada. Pipα queda como opcion adicional y no realiza autenticacion.' -ForegroundColor Green
        Write-Host 'Para retirar la integracion: .\uninstall.ps1'
    }
} catch {
    if ($createdInprocKey) { $registryBase.DeleteSubKeyTree($InprocRegistryPath, $false) }
    if ($createdClsidKey) { $registryBase.DeleteSubKeyTree($ClsidRegistryPath, $false) }
    if ($createdProviderKey) { $registryBase.DeleteSubKeyTree($ProviderRegistryPath, $false) }
    if ($copiedDll -and (Test-Path -LiteralPath $InstalledDllPath)) { Remove-Item -LiteralPath $InstalledDllPath -Force }
    if (Test-Path -LiteralPath $InstallRoot) {
        $remaining = @(Get-ChildItem -LiteralPath $InstallRoot -Force)
        if ($remaining.Count -eq 0) { Remove-Item -LiteralPath $InstallRoot -Force }
    }
    throw
} finally {
    $registryBase.Dispose()
}
