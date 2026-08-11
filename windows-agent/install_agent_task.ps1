#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$TaskName = 'Pipa Windows Agent',
    [string]$TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$launcher = Join-Path $PSScriptRoot 'start_agent_hidden.ps1'
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "No se encuentra el lanzador silencioso: $launcher"
}

if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) {
    throw "No se encuentra Windows PowerShell: $powershell"
}

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -eq $task) {
    throw "No se encuentra la tarea '$TaskPath$TaskName'. Indica el nombre correcto con -TaskName."
}

$arguments = '-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $launcher
$actionDescription = "Ejecutar PowerShell oculto usando $launcher"

if ($PSCmdlet.ShouldProcess("$TaskPath$TaskName", $actionDescription)) {
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
    Set-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $action | Out-Null
    Write-Host "Tarea actualizada: $TaskPath$TaskName"
    Write-Host "Accion: $powershell $arguments"
}
