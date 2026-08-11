Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$agentDirectory = $PSScriptRoot
$mainScript = Join-Path $agentDirectory 'main.py'

if (-not (Test-Path -LiteralPath $mainScript -PathType Leaf)) {
    throw "No se encuentra el agente: $mainScript"
}

$existingAgent = $null
try {
    $existingAgent = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/' -TimeoutSec 2
} catch {
    $existingAgent = $null
}
if ($null -ne $existingAgent -and $existingAgent.name -eq 'Pipα Windows Agent') {
    exit 0
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
