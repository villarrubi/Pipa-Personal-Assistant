[CmdletBinding()]
param(
    [string] $TaskName = 'Pipa Windows Agent',
    [string] $TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Tarea:       no instalada ($TaskPath$TaskName)" -ForegroundColor Yellow
} else {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath
    Write-Host "Tarea:       $($task.State)"
    Write-Host "Ultimo inicio: $($taskInfo.LastRunTime)"
    Write-Host "Resultado:   $($taskInfo.LastTaskResult)"
}

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/status' -TimeoutSec 3
    $protocol = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/pipa/protocol' -TimeoutSec 3
    if (-not $health.success) { throw 'La API respondió sin success=true.' }
    $protocolProperties = @($protocol.PSObject.Properties.Name)
    $usbConfigured = if ($protocolProperties -contains 'serial_gateway_configured') {
        $protocol.serial_gateway_configured
    } else {
        $protocol.serial_gateway
    }
    $usbRunning = if ($protocolProperties -contains 'serial_gateway_running') {
        $protocol.serial_gateway_running
    } else {
        $protocol.serial_gateway
    }
    Write-Host 'Agente:      online' -ForegroundColor Green
    Write-Host "Sesiones:    $($protocol.connected_sessions)"
    Write-Host "USB config.: $usbConfigured"
    Write-Host "USB activo:  $usbRunning"
} catch {
    Write-Host 'Agente:      offline' -ForegroundColor Red
    $logPath = Join-Path $env:LOCALAPPDATA 'Pipa\logs\agent.log'
    Write-Host "Log local:   $logPath"
    exit 1
}

$logPath = Join-Path $env:LOCALAPPDATA 'Pipa\logs\agent.log'
Write-Host "Log local:   $logPath"
