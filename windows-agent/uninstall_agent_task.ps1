[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string] $TaskName = 'Pipa Windows Agent',
    [string] $TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runKeyPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runValueName = 'Pipa Windows Agent'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$startupShortcut = Join-Path $startupDirectory 'Pipa Windows Agent.lnk'

$task = $null
try {
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
} catch {
    Write-Verbose "No se pudo consultar el Programador de tareas: $($_.Exception.Message)"
}
if ($null -eq $task) {
    Write-Host "La tarea '$TaskPath$TaskName' no esta instalada."
} elseif ($PSCmdlet.ShouldProcess("$TaskPath$TaskName", 'Detener y eliminar la tarea de inicio de Pipa')) {
    try {
        Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
        Write-Host "Tarea eliminada: $TaskPath$TaskName" -ForegroundColor Green
    } catch {
        Write-Warning "No se pudo eliminar la tarea '$TaskPath$TaskName': $($_.Exception.Message)"
    }
}

if (Test-Path -LiteralPath $runKeyPath) {
    $runValue = Get-ItemProperty -Path $runKeyPath -Name $runValueName -ErrorAction SilentlyContinue
    if ($null -ne $runValue -and $PSCmdlet.ShouldProcess("HKCU Run/$runValueName", 'Eliminar el inicio oculto de Pipa')) {
        Remove-ItemProperty -Path $runKeyPath -Name $runValueName -Force
        Write-Host "Inicio de sesion eliminado: HKCU/$runValueName" -ForegroundColor Green
    }
}

if ((Test-Path -LiteralPath $startupShortcut -PathType Leaf) -and
    $PSCmdlet.ShouldProcess($startupShortcut, 'Eliminar el acceso directo de inicio de Pipa')) {
    Remove-Item -LiteralPath $startupShortcut -Force
    Write-Host "Inicio de sesion eliminado: $startupShortcut" -ForegroundColor Green
}
