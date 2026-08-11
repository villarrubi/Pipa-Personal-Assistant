Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$agentDirectory = $PSScriptRoot
$mainScript = Join-Path $agentDirectory 'main.py'

if (-not (Test-Path -LiteralPath $mainScript -PathType Leaf)) {
    throw "No se encuentra el agente: $mainScript"
}

$pythonLauncher = $null
foreach ($candidate in @('pyw.exe', 'pythonw.exe')) {
    $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $command) {
        $pythonLauncher = $command
        break
    }
}

if ($null -eq $pythonLauncher) {
    throw 'No se encuentra pyw.exe ni pythonw.exe en el PATH del usuario.'
}

$quotedScript = '"{0}"' -f $mainScript
Start-Process -FilePath $pythonLauncher.Source `
    -ArgumentList $quotedScript `
    -WorkingDirectory $agentDirectory `
    -WindowStyle Hidden
