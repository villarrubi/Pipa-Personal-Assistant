#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$TaskName = 'Pipa Windows Agent',
    [string]$TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$launcher = Join-Path $PSScriptRoot 'start_agent.vbs'
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "No se encuentra el lanzador silencioso: $launcher"
}

if (-not (Test-Path -LiteralPath $wscript -PathType Leaf)) {
    throw "No se encuentra wscript.exe: $wscript"
}

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -eq $task) {
    throw "No se encuentra la tarea '$TaskPath$TaskName'. Indica el nombre correcto con -TaskName."
}

$arguments = '"{0}"' -f $launcher
$actionDescription = "Ejecutar wscript.exe sin ventana usando $launcher"

if ($PSCmdlet.ShouldProcess("$TaskPath$TaskName", $actionDescription)) {
    $action = New-ScheduledTaskAction -Execute $wscript -Argument $arguments
    Set-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $action | Out-Null
    Write-Host "Tarea actualizada: $TaskPath$TaskName"
    Write-Host "Accion: $wscript $arguments"
}
