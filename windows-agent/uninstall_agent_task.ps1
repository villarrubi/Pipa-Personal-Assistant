#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string] $TaskName = 'Pipa Windows Agent',
    [string] $TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "La tarea '$TaskPath$TaskName' no está instalada."
    exit 0
}

if ($PSCmdlet.ShouldProcess("$TaskPath$TaskName", 'Detener y eliminar la tarea de inicio de Pipa')) {
    Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
    Write-Host "Tarea eliminada: $TaskPath$TaskName" -ForegroundColor Green
}
