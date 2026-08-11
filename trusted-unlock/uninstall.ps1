[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [switch] $KeepBinary
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProviderGuid = '{7D886843-37F4-4C64-A45A-8550F112E57A}'
$ProviderName = 'Pipa Trusted Unlock'
$ClsidDisplayName = "$ProviderName Credential Provider"
$ExpectedThreadingModel = 'Apartment'
$InstallRoot = Join-Path ${env:ProgramFiles} 'Pipa\TrustedUnlock'
$InstalledDllPath = Join-Path $InstallRoot 'PipaTrustedUnlock.dll'
$ProviderRegistryPath = "SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$ProviderGuid"
$ClsidRegistryPath = "SOFTWARE\Classes\CLSID\$ProviderGuid"
$InprocRegistryPath = "$ClsidRegistryPath\InprocServer32"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    throw 'Ejecuta uninstall.ps1 en PowerShell como administrador.'
}

$registryBase = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
    [Microsoft.Win32.RegistryHive]::LocalMachine,
    [Microsoft.Win32.RegistryView]::Registry64
)

try {
    $providerKey = $registryBase.OpenSubKey($ProviderRegistryPath, $false)
    $clsidKey = $registryBase.OpenSubKey($ClsidRegistryPath, $false)
    $inprocKey = $registryBase.OpenSubKey($InprocRegistryPath, $false)

    $registrationExists =
        $null -ne $providerKey -or
        $null -ne $clsidKey -or
        $null -ne $inprocKey

    try {
        if (-not $registrationExists) {
            Write-Host 'No hay registro de Pipα. Solo se revisara la DLL instalada.'
        }

        if ($registrationExists) {
            if ($null -eq $providerKey -or $null -eq $clsidKey -or $null -eq $inprocKey) {
                throw 'La instalación está incompleta; no se eliminará ninguna clave automáticamente.'
            }

            $registeredProviderName = [string]$providerKey.GetValue('', '')
            $registeredClsidName = [string]$clsidKey.GetValue('', '')
            $registeredDll = [string]$inprocKey.GetValue('', '')
            $registeredThreadingModel = [string]$inprocKey.GetValue('ThreadingModel', '')
            $clsidSubKeys = @($clsidKey.GetSubKeyNames())

            if ($registeredProviderName -ne $ProviderName -or
                $registeredClsidName -ne $ClsidDisplayName -or
                -not [string]::Equals($registeredDll, $InstalledDllPath, [StringComparison]::OrdinalIgnoreCase) -or
                $registeredThreadingModel -ne $ExpectedThreadingModel -or
                $clsidSubKeys.Count -ne 1 -or
                $clsidSubKeys[0] -ne 'InprocServer32') {
                throw "La instalación no coincide exactamente con Pipα; no se eliminará ninguna clave."
            }
        }
    } finally {
        if ($null -ne $providerKey) { $providerKey.Dispose() }
        if ($null -ne $clsidKey) { $clsidKey.Dispose() }
        if ($null -ne $inprocKey) { $inprocKey.Dispose() }
    }

    Write-Host "Se eliminara: HKLM\$ProviderRegistryPath"
    Write-Host "Se eliminara: HKLM\$ClsidRegistryPath"
    if (-not $KeepBinary) { Write-Host "Se eliminara: $InstalledDllPath" }

    if ($PSCmdlet.ShouldProcess("HKLM:\$ProviderRegistryPath y HKLM:\$ClsidRegistryPath", 'Eliminar Credential Provider adicional')) {
        $providerKeyToDelete = $registryBase.OpenSubKey($ProviderRegistryPath, $false)
        if ($null -ne $providerKeyToDelete) {
            $providerKeyToDelete.Dispose()
            $registryBase.DeleteSubKeyTree($ProviderRegistryPath, $false)
        }
        $clsidKeyToDelete = $registryBase.OpenSubKey($ClsidRegistryPath, $false)
        if ($null -ne $clsidKeyToDelete) {
            $clsidKeyToDelete.Dispose()
            $registryBase.DeleteSubKeyTree($ClsidRegistryPath, $false)
        }
    }

    if (-not $KeepBinary -and $PSCmdlet.ShouldProcess($InstalledDllPath, 'Eliminar DLL instalada')) {
        if (Test-Path -LiteralPath $InstalledDllPath) {
            Remove-Item -LiteralPath $InstalledDllPath -Force
        }
        if (Test-Path -LiteralPath $InstallRoot) {
            $remaining = @(Get-ChildItem -LiteralPath $InstallRoot -Force)
            if ($remaining.Count -eq 0) { Remove-Item -LiteralPath $InstallRoot -Force }
        }
    }

    if (-not $WhatIfPreference) {
        Write-Host 'Pipα ha sido retirado. Los providers normales de Windows no se han modificado.' -ForegroundColor Green
    }
} finally {
    $registryBase.Dispose()
}
