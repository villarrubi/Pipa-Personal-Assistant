[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$TaskName = 'Pipa Windows Agent',
    [string]$TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This is intentionally a per-user, limited task. It must not run elevated.

$launcher = Join-Path $PSScriptRoot 'start_agent_hidden.ps1'
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "No se encuentra el lanzador silencioso: $launcher"
}

if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) {
    throw "No se encuentra Windows PowerShell: $powershell"
}

$expectedArguments = '-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $launcher
$arguments = $expectedArguments
$actionDescription = "Ejecutar PowerShell oculto usando $launcher"
$runKeyPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runValueName = 'Pipa Windows Agent'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$startupShortcut = Join-Path $startupDirectory 'Pipa Windows Agent.lnk'
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$currentUser = [string]$currentIdentity.Name
$currentUserLeaf = ($currentUser -split '\\')[-1]
$currentUserSid = if ($null -ne $currentIdentity.User) {
    [string]$currentIdentity.User.Value
} else {
    ''
}

function Test-CurrentUserPrincipal {
    param([string]$Value)

    return (
        [string]::Equals($Value, $currentUser, [StringComparison]::OrdinalIgnoreCase) -or
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
    param(
        [Parameter(Mandatory = $false)] [object]$Task
    )

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
        [string]::Equals([string]$action.Execute, $powershell, [StringComparison]::OrdinalIgnoreCase) -and
        [string]::Equals([string]$action.Arguments, $arguments, [StringComparison]::Ordinal)
    $limitedPrincipal = [string]$Task.Principal.RunLevel -notmatch '(?i)Highest|Admin'
    $currentUserPrincipal = Test-CurrentUserPrincipal ([string]$Task.Principal.UserId)
    return $exactAction -and $limitedPrincipal -and $currentUserPrincipal
}

function Remove-PipaFallbacks {
    if (Test-Path -LiteralPath $runKeyPath) {
        $runValue = Get-ItemProperty -Path $runKeyPath -Name $runValueName -ErrorAction SilentlyContinue
        if ($null -ne $runValue -and $runValue.PSObject.Properties.Name -contains $runValueName) {
            Remove-ItemProperty -Path $runKeyPath -Name $runValueName -Force -ErrorAction SilentlyContinue
            Write-Verbose "Fallback HKCU Run eliminado: $runValueName"
        }
    }
    if (Test-Path -LiteralPath $startupShortcut -PathType Leaf) {
        Remove-Item -LiteralPath $startupShortcut -Force -ErrorAction SilentlyContinue
        Write-Verbose "Fallback Startup eliminado: $startupShortcut"
    }
}

function Register-WithSchtasks {
    param(
        [Parameter(Mandatory)] [string]$FullTaskName,
        [Parameter(Mandatory)] [string]$UserName,
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(Mandatory)] [string]$ActionArguments
    )

    $schtasks = Join-Path $env:WINDIR 'System32\schtasks.exe'
    if (-not (Test-Path -LiteralPath $schtasks -PathType Leaf)) {
        throw "No se encuentra schtasks.exe: $schtasks"
    }

    $taskCommand = '"{0}" {1}' -f $Executable, $ActionArguments
    $legacyArguments = @(
        '/Create',
        '/TN', $FullTaskName,
        '/SC', 'ONLOGON',
        '/TR', $taskCommand,
        '/RU', $UserName,
        '/RL', 'LIMITED',
        '/F'
    )
    $output = & $schtasks @legacyArguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo registrar la tarea con schtasks.exe: $($output -join ' ')"
    }
    Write-Host "Tarea registrada mediante schtasks.exe: $FullTaskName"
}

function Register-WithUserRun {
    param(
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(Mandatory)] [string]$ActionArguments
    )

    if (-not (Test-Path -LiteralPath $runKeyPath)) {
        New-Item -Path $runKeyPath -Force | Out-Null
    }
    $command = '"{0}" {1}' -f $Executable, $ActionArguments
    Set-ItemProperty -Path $runKeyPath -Name $runValueName -Value $command -Type String
    Write-Host "Inicio de sesion registrado en HKCU: $runValueName"
}

function Register-WithStartupShortcut {
    param(
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(Mandatory)] [string]$ActionArguments
    )

    if ([string]::IsNullOrWhiteSpace($startupDirectory) -or
        -not (Test-Path -LiteralPath $startupDirectory -PathType Container)) {
        throw "No se encuentra la carpeta de Inicio del usuario: $startupDirectory"
    }
    $shell = $null
    $shortcut = $null
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($startupShortcut)
        $shortcut.TargetPath = $Executable
        $shortcut.Arguments = $ActionArguments
        $shortcut.WorkingDirectory = $PSScriptRoot
        $shortcut.WindowStyle = 7
        $shortcut.Description = 'Pipa Windows Agent (inicio oculto)'
        $shortcut.Save()
        Write-Host "Inicio de sesion registrado en Startup: $startupShortcut"
    } finally {
        if ($null -ne $shortcut) {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut)
        }
        if ($null -ne $shell) {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
        }
    }
}

if ($PSCmdlet.ShouldProcess("$TaskPath$TaskName", $actionDescription)) {
    $fullTaskName = "$TaskPath$TaskName"
    $existingTask = $null
    try {
        $existingTask = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction Stop
    } catch {
        $existingTask = $null
    }

    if ($null -ne $existingTask -and (Test-SafeTask -Task $existingTask)) {
        Remove-PipaFallbacks
        Write-Host "Tarea verificada: $fullTaskName"
    } else {
        try {
            $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -ErrorAction Stop
            $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser -ErrorAction Stop
            $principal = New-ScheduledTaskPrincipal `
                -UserId $currentUser `
                -LogonType Interactive `
                -RunLevel Limited `
                -ErrorAction Stop
            $settings = New-ScheduledTaskSettingsSet `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) `
                -RestartCount 3 `
                -RestartInterval (New-TimeSpan -Minutes 1) `
                -ErrorAction Stop
            # Re-register the complete definition so stale visible/elevated settings cannot survive.
            Register-ScheduledTask `
                -TaskName $TaskName `
                -TaskPath $TaskPath `
                -Action $action `
                -Trigger $trigger `
                -Settings $settings `
                -Principal $principal `
                -Force `
                -ErrorAction Stop | Out-Null
            Remove-PipaFallbacks
            $verb = if ($null -eq $existingTask) { 'creada' } else { 'actualizada' }
            Write-Host "Tarea $verb`: $fullTaskName"
        } catch {
            # Some Windows installations deny the PowerShell ScheduledTasks CIM
            # provider to standard users even for a limited interactive task.
            # schtasks.exe can create the same non-elevated definition.
            Write-Verbose "ScheduledTasks cmdlets no disponibles: $($_.Exception.Message)"
            try {
                Register-WithSchtasks `
                    -FullTaskName $fullTaskName `
                    -UserName $currentUser `
                    -Executable $powershell `
                    -ActionArguments $arguments
                Remove-PipaFallbacks
            } catch {
                Write-Verbose "schtasks.exe no disponible: $($_.Exception.Message)"
                if ($null -ne $existingTask) {
                    throw "La tarea existente '$fullTaskName' no se pudo verificar ni actualizar; no se instala un fallback ambiguo."
                }
                try {
                    Register-WithUserRun -Executable $powershell -ActionArguments $arguments
                } catch {
                    Write-Verbose "HKCU Run no disponible: $($_.Exception.Message)"
                    Register-WithStartupShortcut -Executable $powershell -ActionArguments $arguments
                }
            }
        }
    }
    Write-Host "Accion: $powershell $arguments"

    # Re-registration does not terminate a process started by the previous
    # task definition. Reload only the exact Pipa main.py process so an update
    # cannot leave an older agent serving the local API.
    $reloadArguments = @(
        '-NoLogo',
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $launcher,
        '-Restart'
    )
    $reloadOutput = & $powershell @reloadArguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo recargar el agente Pipa: $($reloadOutput -join ' ')"
    }
    Write-Host 'Agente recargado con el codigo actual.'
}
