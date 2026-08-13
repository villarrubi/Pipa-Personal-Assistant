[CmdletBinding()]
param(
    [switch]$Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$agentDirectory = $PSScriptRoot
$mainScript = Join-Path $agentDirectory 'main.py'

if (-not (Test-Path -LiteralPath $mainScript -PathType Leaf)) {
    throw "No se encuentra el agente: $mainScript"
}
$mainScript = (Resolve-Path -LiteralPath $mainScript).Path

function Get-PipaAgentProcesses {
    try {
        $processes = @(Get-CimInstance Win32_Process `
            -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" `
            -ErrorAction Stop)
        return @(
            $processes | Where-Object {
                $commandLine = [string]$_.CommandLine
                $hasExactScript = $commandLine.IndexOf(
                    ('-B "{0}"' -f $mainScript),
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -ge 0
                $hasKnownInterpreter = [string]$_.Name -in @('python.exe', 'pythonw.exe')
                $hasExactScript -and $hasKnownInterpreter
            }
        )
    } catch {
        # Non-elevated PowerShell may not read Win32_Process.CommandLine. Do
        # not infer identity from an interpreter path and never stop a Python
        # process by approximation. The loopback listener check below is the
        # safe fallback for the restart case.
        return @()
    }
}

function Get-PipaLoopbackListenerProcessIds {
    # Get-NetTCPConnection is CIM-backed and may be unavailable to a normal
    # user. netstat is read-only here; these PIDs are used only to wait for the
    # exact agent's graceful shutdown and to detect an occupied port. They are
    # never stopped directly.
    $lines = @(netstat.exe -ano -p tcp 2>$null)
    $processIds = [System.Collections.Generic.List[int]]::new()
    foreach ($line in $lines) {
        if ($line -match '^\s*TCP\s+127\.0\.0\.1:8765\s+\S+\s+(?:LISTENING|ESCUCHANDO)\s+(\d+)\s*$') {
            $processIds.Add([int]$Matches[1])
        }
    }
    return @($processIds | Sort-Object -Unique)
}

function Stop-PipaProcessId {
    param(
        [Parameter(Mandatory)] [int]$ProcessId,
        [switch]$Force
    )

    if ($ProcessId -le 0) {
        return
    }
    # A listener can disappear between netstat and Stop-Process. Treat that
    # race as already stopped, but never stop a PID that was not revalidated.
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            return
        }
        $resolvedProcessId = $process.Id
        if ($null -eq $resolvedProcessId) {
            return
        }
        # The process may exit after the read and before Stop-Process. That is
        # an idempotent success; the caller rechecks the exact listener after
        # this function and still fails closed if it remains alive.
        $stopParameters = @{
            Id = [int]$resolvedProcessId
            ErrorAction = 'SilentlyContinue'
        }
        if ($Force) {
            $stopParameters.Force = $true
        }
        Stop-Process @stopParameters
    } catch {
        Write-Verbose "El proceso $ProcessId ya no estaba disponible para detenerlo: $($_.Exception.Message)"
    }
}

function Wait-PipaLoopbackListenerStopped {
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while (@(Get-PipaLoopbackListenerProcessIds).Count -gt 0 -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 200
    }
    return @(Get-PipaLoopbackListenerProcessIds).Count -eq 0
}

function Request-PipaGracefulReload {
    try {
        $headers = @{
            'X-Pipa-Local-Request' = '1'
            'X-Pipa-Reload' = '1'
        }
        $response = Invoke-WebRequest `
            -Uri 'http://127.0.0.1:8765/internal/reload' `
            -Method Post `
            -Headers $headers `
            -TimeoutSec 2 `
            -UseBasicParsing `
            -ErrorAction Stop
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
            return $false
        }
        return Wait-PipaLoopbackListenerStopped
    } catch {
        return $false
    }
}

function Stop-PipaAgentProcesses {
    param(
        [Parameter(Mandatory)] [object[]]$Processes
    )

    foreach ($process in $Processes) {
        if ($null -ne $process -and $null -ne $process.ProcessId) {
            Stop-PipaProcessId -ProcessId ([int]$process.ProcessId)
        }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $remaining = @(Get-PipaAgentProcesses)
        if ($remaining.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)

    # A stuck old process must not leave the installer spawning a duplicate.
    # The process list is revalidated by the same exact command-line match.
    foreach ($process in @(Get-PipaAgentProcesses)) {
        if ($null -ne $process -and $null -ne $process.ProcessId) {
            # The command line is revalidated immediately above. Force is
            # limited to that exact Pipa process; never use a listener PID or
            # a name-only match as a restart target.
            Stop-PipaProcessId -ProcessId ([int]$process.ProcessId) -Force
        }
    }
    if (@(Get-PipaAgentProcesses).Count -gt 0) {
        throw 'No se pudo cerrar el proceso antiguo del agente Pipa.'
    }
}

$existingAgent = $null
try {
    $existingAgent = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/' -TimeoutSec 2
} catch {
    $existingAgent = $null
}
$isCurrentAgent = $null -ne $existingAgent -and
    $existingAgent.service -eq 'pipa-windows-agent' -and
    $existingAgent.status -eq 'online' -and
    $null -ne $existingAgent.version
$isLegacyAgent = $null -ne $existingAgent -and
    $existingAgent.status -eq 'online' -and
    $null -ne $existingAgent.version -and
    $existingAgent.name -like '*Windows Agent'
$gracefulReloaded = $false
if ($isCurrentAgent -or $isLegacyAgent) {
    if (-not $Restart) {
        exit 0
    }
    if (-not (Request-PipaGracefulReload)) {
        try {
            $knownAgentProcesses = @(Get-PipaAgentProcesses)
        } catch {
            throw "No se pudo inspeccionar el proceso exacto del agente para recargarlo: $($_.Exception.Message)"
        }
        if ($knownAgentProcesses.Count -eq 0) {
            throw 'No se pudo verificar la linea de comandos exacta del agente; no se detiene el listener local.'
        }
        Stop-PipaAgentProcesses -Processes $knownAgentProcesses
    } else {
        $gracefulReloaded = $true
    }
}

$agentProcesses = @()
if (-not $gracefulReloaded) {
    try {
        $agentProcesses = @(Get-PipaAgentProcesses)
    } catch {
        if ($Restart) {
            throw "No se pudo inspeccionar el proceso del agente para recargarlo: $($_.Exception.Message)"
        }
    }
}
if ($agentProcesses.Count -gt 0) {
    Stop-PipaAgentProcesses -Processes $agentProcesses
}
if (@(Get-PipaLoopbackListenerProcessIds).Count -gt 0) {
    throw 'El puerto local 8765 sigue ocupado; no se iniciara otro agente.'
}

$pythonExecutable = $null
$venvLauncher = Join-Path $agentDirectory '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $venvLauncher -PathType Leaf) {
    $pythonExecutable = $venvLauncher
}
foreach ($candidate in @('pyw.exe', 'pythonw.exe')) {
    if ($null -ne $pythonExecutable) { break }
    $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $command) {
        $pythonExecutable = $command.Source
        break
    }
}

if ($null -eq $pythonExecutable) {
    throw 'No se encuentra pyw.exe ni pythonw.exe en el PATH del usuario.'
}

$arguments = '-B "{0}"' -f $mainScript
Start-Process -FilePath $pythonExecutable `
    -ArgumentList $arguments `
    -WorkingDirectory $agentDirectory `
    -WindowStyle Hidden
