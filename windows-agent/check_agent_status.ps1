[CmdletBinding()]
param(
    [string] $TaskName = 'Pipa Windows Agent',
    [string] $TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$task = $null
$taskQueryFailed = $false
try {
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction Stop
} catch {
    # The cmdlet can be unavailable or denied to a standard user. Let the
    # schtasks XML fallback distinguish a real missing task from an unreadable
    # scheduler, instead of silently reporting a secure task as absent.
    $taskQueryFailed = $true
}
$taskXml = $null
if ($null -eq $task) {
    # The ScheduledTasks CIM provider is unavailable in some constrained
    # PowerShell sessions. Use schtasks XML as a read-only fallback so a
    # correctly installed task is not reported as missing.
    $schtasks = Join-Path $env:WINDIR 'System32\schtasks.exe'
    if (Test-Path -LiteralPath $schtasks -PathType Leaf) {
        try {
            $xmlOutput = @(& $schtasks /Query /TN "$TaskPath$TaskName" /XML 2>&1)
            $xmlText = $xmlOutput -join "`n"
            $taskMissing = $xmlText -match '(?i)(cannot find|no puede encontrar|no se puede encontrar|no existe|not exist|path specified|ruta especificada)'
            if ($LASTEXITCODE -eq 0 -and $xmlOutput.Count -gt 0) {
                $taskXml = [xml]$xmlText
                $taskQueryFailed = $false
            } elseif ($taskMissing) {
                # A missing task is a valid, verifiable state. Do not keep
                # the earlier Get-ScheduledTask failure as if the scheduler
                # were inaccessible.
                $taskQueryFailed = $false
            } else {
                $taskQueryFailed = $true
            }
        } catch {
            $taskXml = $null
            $taskQueryFailed = $true
        }
    } else {
        $taskQueryFailed = $true
    }
}
$runKeyPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runValueName = 'Pipa Windows Agent'
$expectedLauncher = Join-Path $PSScriptRoot 'start_agent_hidden.ps1'
$expectedPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$expectedArguments = '-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $expectedLauncher
$startupDirectory = [Environment]::GetFolderPath('Startup')
$startupShortcut = Join-Path $startupDirectory 'Pipa Windows Agent.lnk'
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

function Get-SafeFallbackProfile {
    $runValue = Get-ItemProperty -Path $runKeyPath -Name $runValueName -ErrorAction SilentlyContinue
    $runCommand = if ($null -ne $runValue -and
        $runValue.PSObject.Properties.Name -contains $runValueName) {
        [string]$runValue.$runValueName
    } else {
        ''
    }
    $expectedRunCommand = '"{0}" {1}' -f $expectedPowerShell, $expectedArguments
    $safeRun = [string]::Equals($runCommand, $expectedRunCommand, [StringComparison]::Ordinal)

    $safeShortcut = $false
    if (Test-Path -LiteralPath $startupShortcut -PathType Leaf) {
        $shell = $null
        $shortcut = $null
        try {
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($startupShortcut)
            $shortcutArguments = [string]$shortcut.Arguments
            $safeShortcut = [string]::Equals(
                [string]$shortcut.TargetPath,
                $expectedPowerShell,
                [StringComparison]::OrdinalIgnoreCase
            ) -and [string]::Equals($shortcutArguments, $expectedArguments, [StringComparison]::Ordinal)
        } catch {
            $safeShortcut = $false
        } finally {
            if ($null -ne $shortcut) {
                [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut)
            }
            if ($null -ne $shell) {
                [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
            }
        }
    }

    if ($safeRun) { return 'HKCU Run' }
    if ($safeShortcut) { return 'Startup' }
    return 'none'
}

$fallbackProfile = Get-SafeFallbackProfile
if ($null -ne $taskXml) {
    $xmlAction = $taskXml.Task.Actions.Exec
    $xmlPrincipal = $taskXml.Task.Principals.Principal
    $xmlLogonTrigger = $taskXml.Task.Triggers.LogonTrigger
    $xmlCommand = [string]$xmlAction.Command
    $xmlArguments = [string]$xmlAction.Arguments
    $xmlRunLevel = [string]$xmlPrincipal.RunLevel
    $xmlUserId = [string]$xmlPrincipal.UserId
    # LeastPrivilege is the XML default when RunLevel is omitted.
    $xmlLimited = [string]::IsNullOrWhiteSpace($xmlRunLevel) -or $xmlRunLevel -eq 'LeastPrivilege'
    $xmlExactAction = [string]::Equals(
        $xmlCommand,
        $expectedPowerShell,
        [StringComparison]::OrdinalIgnoreCase
    ) -and [string]::Equals($xmlArguments, $expectedArguments, [StringComparison]::Ordinal)
    # Task XML commonly stores UserId as the current user's SID, while the
    # ScheduledTasks object may expose the DOMAIN\\user name. Accept only
    # either exact representation of this same Windows identity.
    $xmlCurrentUser = Test-CurrentUserId $xmlUserId
    $xmlSafeTask = $xmlExactAction -and $xmlLimited -and $xmlCurrentUser -and $null -ne $xmlLogonTrigger
    Write-Host "Tarea:       Ready"
    $xmlSafeTaskText = if ($xmlSafeTask) { 'OK' } else { 'REVISAR' }
    $xmlSafeTaskColor = if ($xmlSafeTask) { 'Green' } else { 'Yellow' }
    Write-Host "Perfil inicio oculto/limitado: $xmlSafeTaskText" -ForegroundColor $xmlSafeTaskColor
    if ($fallbackProfile -ne 'none') {
        Write-Host "Fallback de inicio duplicado: $fallbackProfile" -ForegroundColor Yellow
    } else {
        Write-Host 'Fallback de inicio: ninguno' -ForegroundColor Green
    }
} elseif ($null -eq $task) {
    if ($taskQueryFailed) {
        Write-Host 'Tarea:       no se pudo consultar el Programador de tareas' -ForegroundColor Yellow
    } else {
        Write-Host "Tarea:       no instalada ($TaskPath$TaskName)" -ForegroundColor Yellow
    }
    if ($fallbackProfile -eq 'HKCU Run') {
        Write-Host 'Inicio HKCU oculto/limitado: OK' -ForegroundColor Green
        Write-Host 'Perfil inicio oculto/limitado: OK (fallback HKCU)' -ForegroundColor Green
    } elseif ($fallbackProfile -eq 'Startup') {
        Write-Host 'Inicio Startup oculto/limitado: OK' -ForegroundColor Green
        Write-Host 'Perfil inicio oculto/limitado: OK (fallback Startup)' -ForegroundColor Green
    } elseif ($taskQueryFailed) {
        Write-Host 'Perfil inicio oculto/limitado: NO VERIFICADO (Programador inaccesible)' -ForegroundColor Yellow
        Write-Host 'Fallback de inicio: ninguno verificable' -ForegroundColor Yellow
    } else {
        Write-Host 'Inicio HKCU/Startup oculto/limitado: no instalado' -ForegroundColor Yellow
        Write-Host 'Perfil inicio oculto/limitado: NO INSTALADO' -ForegroundColor Yellow
        Write-Host 'Fallback de inicio: ninguno' -ForegroundColor Yellow
    }
} else {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath
    Write-Host "Tarea:       $($task.State)"
    Write-Host "Ultimo inicio: $($taskInfo.LastRunTime)"
    Write-Host "Resultado:   $($taskInfo.LastTaskResult)"

    $action = @($task.Actions) | Select-Object -First 1
    $trigger = @($task.Triggers) |
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
    $exactAction = $null -ne $action -and
        [string]::Equals([string]$action.Execute, $expectedPowerShell, [StringComparison]::OrdinalIgnoreCase) -and
        [string]::Equals([string]$action.Arguments, $expectedArguments, [StringComparison]::Ordinal)
    $limitedPrincipal = $task.Principal.RunLevel -notmatch '(?i)Highest|Admin'
    $currentUserPrincipal = Test-CurrentUserId ([string]$task.Principal.UserId)
    $safeTask = $exactAction -and $limitedPrincipal -and $currentUserPrincipal -and $null -ne $trigger
    $profileStatus = if ($safeTask) { 'OK' } else { 'REVISAR' }
    $profileColor = if ($safeTask) { 'Green' } else { 'Yellow' }
    Write-Host "Perfil inicio oculto/limitado: $profileStatus" -ForegroundColor $profileColor

    if ($fallbackProfile -ne 'none') {
        Write-Host "Fallback de inicio duplicado: $fallbackProfile" -ForegroundColor Yellow
    } else {
        Write-Host 'Fallback de inicio: ninguno' -ForegroundColor Green
    }
}

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/status' -TimeoutSec 3
    $protocol = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/pipa/protocol' -TimeoutSec 3
    if (-not $health.success) { throw 'La API respondio sin success=true.' }
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
    $mobileConfigured = if ($protocolProperties -contains 'mobile_gateway_configured') {
        $protocol.mobile_gateway_configured
    } else {
        $false
    }
    $mobileRunning = if ($protocolProperties -contains 'mobile_gateway_running') {
        $protocol.mobile_gateway_running
    } else {
        $false
    }
    Write-Host 'Agente:      online' -ForegroundColor Green
    Write-Host "Sesiones:    $($protocol.connected_sessions)"
    Write-Host "USB config.: $usbConfigured"
    Write-Host "USB activo:  $usbRunning"
    Write-Host "Movil config.: $mobileConfigured"
    Write-Host "Movil activo:  $mobileRunning"
} catch {
    Write-Host 'Agente:      offline' -ForegroundColor Red
    $logPath = Join-Path $env:LOCALAPPDATA 'Pipa\logs\agent.log'
    Write-Host "Log local:   $logPath"
    exit 1
}

$logPath = Join-Path $env:LOCALAPPDATA 'Pipa\logs\agent.log'
Write-Host "Log local:   $logPath"
