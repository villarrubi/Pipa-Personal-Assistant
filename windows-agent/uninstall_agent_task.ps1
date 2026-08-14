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
$expectedPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$expectedLauncher = Join-Path $PSScriptRoot 'start_agent_hidden.ps1'
$expectedArguments = '-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $expectedLauncher
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$currentUserName = [string]$currentIdentity.Name
$currentUserLeaf = ($currentUserName -split '\\')[-1]
$currentUserSid = if ($null -ne $currentIdentity.User) {
    [string]$currentIdentity.User.Value
} else {
    ''
}

function Test-CurrentUserId {
    param([string]$Value)

    return (
        [string]::Equals($Value, $currentUserName, [StringComparison]::OrdinalIgnoreCase) -or
        (
            $Value.IndexOf('\', [StringComparison]::Ordinal) -lt 0 -and
            [string]::Equals($Value, $currentUserLeaf, [StringComparison]::OrdinalIgnoreCase)
        ) -or
        (
            -not [string]::IsNullOrWhiteSpace($currentUserSid) -and
            [string]::Equals($Value, $currentUserSid, [StringComparison]::OrdinalIgnoreCase)
        )
    )
}

function Test-SafeTask {
    param([object]$Task)

    if ($null -eq $Task) { return $false }
    $action = @($Task.Actions) | Select-Object -First 1
    $trigger = @($Task.Triggers) |
        Where-Object {
            $hasTriggerType = $_.PSObject.Properties.Name -contains 'TriggerType'
            $className = if ($null -ne $_.CimClass) {
                [string]$_.CimClass.CimClassName
            } else {
                ''
            }
            ($hasTriggerType -and $_.TriggerType -eq 'Logon') -or
            $className -eq 'MSFT_TaskLogonTrigger'
        } |
        Select-Object -First 1
    if ($null -eq $action -or $null -eq $trigger -or $null -eq $Task.Principal) {
        return $false
    }

    $exactAction =
        [string]::Equals([string]$action.Execute, $expectedPowerShell, [StringComparison]::OrdinalIgnoreCase) -and
        [string]::Equals([string]$action.Arguments, $expectedArguments, [StringComparison]::Ordinal)
    $limitedPrincipal = [string]$Task.Principal.RunLevel -notmatch '(?i)Highest|Admin'
    $currentUserPrincipal = Test-CurrentUserId ([string]$Task.Principal.UserId)
    return $exactAction -and $limitedPrincipal -and $currentUserPrincipal
}

$schtasks = Join-Path $env:WINDIR 'System32\schtasks.exe'
$taskXml = $null
$taskQueryFailed = $false
$taskMissing = $false

$task = $null
try {
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction Stop
} catch {
    $taskQueryFailed = $true
}

if ($null -eq $task -and (Test-Path -LiteralPath $schtasks -PathType Leaf)) {
    $previousErrorAction = $ErrorActionPreference
    try {
        # Native schtasks reports a missing task on its error stream. Capture
        # that output without converting a known absence into an inaccessible
        # scheduler, exactly as the status diagnostic does.
        $ErrorActionPreference = 'Continue'
        $xmlOutput = @(& $schtasks /Query /TN "$TaskPath$TaskName" /XML 2>&1)
        $schtasksExitCode = $LASTEXITCODE
        $xmlText = $xmlOutput -join "`n"
        # A generic "path specified" message can mean that this restricted
        # context cannot read Task Scheduler. Never turn that ambiguity into
        # permission to delete a startup entry.
        $taskMissing = $xmlText -match '(?i)(cannot find (the )?task|no puede encontrar (la )?tarea|no se puede encontrar (la )?tarea|no existe (la )?tarea|task .*not exist|tarea .*no existe|file specified|archivo especificado)'
        if ($schtasksExitCode -eq 0 -and $xmlOutput.Count -gt 0) {
            $taskXml = [xml]$xmlText
            $taskQueryFailed = $false
        } elseif ($taskMissing) {
            $taskQueryFailed = $false
        } else {
            $taskQueryFailed = $true
        }
    } catch {
        $taskXml = $null
        $taskQueryFailed = $true
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
} elseif ($null -eq $task -and -not (Test-Path -LiteralPath $schtasks -PathType Leaf)) {
    $taskQueryFailed = $true
}

$safeTask = $false
if ($null -ne $task) {
    $safeTask = Test-SafeTask -Task $task
} elseif ($null -ne $taskXml) {
    $xmlAction = $taskXml.Task.Actions.Exec
    $xmlPrincipal = $taskXml.Task.Principals.Principal
    $xmlLogonTrigger = $taskXml.Task.Triggers.LogonTrigger
    if ($null -ne $xmlAction -and $null -ne $xmlPrincipal -and $null -ne $xmlLogonTrigger) {
        $xmlExactAction =
            [string]::Equals([string]$xmlAction.Command, $expectedPowerShell, [StringComparison]::OrdinalIgnoreCase) -and
            [string]::Equals([string]$xmlAction.Arguments, $expectedArguments, [StringComparison]::Ordinal)
        $xmlLimited = [string]::IsNullOrWhiteSpace([string]$xmlPrincipal.RunLevel) -or
            [string]$xmlPrincipal.RunLevel -eq 'LeastPrivilege'
        $safeTask = $xmlExactAction -and $xmlLimited -and (Test-CurrentUserId ([string]$xmlPrincipal.UserId))
    }
}

if ($safeTask -and $PSCmdlet.ShouldProcess("$TaskPath$TaskName", 'Detener y eliminar la tarea de inicio de Pipa')) {
    if ($null -ne $task) {
        try {
            Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
            Write-Host "Tarea eliminada: $TaskPath$TaskName" -ForegroundColor Green
        } catch {
            Write-Warning "No se pudo eliminar la tarea '$TaskPath$TaskName': $($_.Exception.Message)"
        }
    } else {
        $deleteOutput = @(& $schtasks /Delete /TN "$TaskPath$TaskName" /F 2>&1)
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Tarea eliminada: $TaskPath$TaskName" -ForegroundColor Green
        } else {
            Write-Warning "No se pudo eliminar la tarea '$TaskPath$TaskName' mediante schtasks.exe."
        }
    }
} elseif ($null -ne $task -or $null -ne $taskXml) {
    Write-Warning "La tarea '$TaskPath$TaskName' existe, pero no coincide exactamente con el inicio limitado de Pipa; no se elimina."
} elseif ($taskQueryFailed) {
    Write-Warning "No se pudo verificar la tarea '$TaskPath$TaskName'; no se elimina por seguridad."
} elseif ($taskMissing -or $null -eq $task) {
    Write-Host "La tarea '$TaskPath$TaskName' no esta instalada."
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
