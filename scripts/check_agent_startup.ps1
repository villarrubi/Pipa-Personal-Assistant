[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcherPath = Join-Path $repoRoot 'windows-agent/start_agent_hidden.ps1'
$installerPath = Join-Path $repoRoot 'windows-agent/install_agent_task.ps1'
$uninstallerPath = Join-Path $repoRoot 'windows-agent/uninstall_agent_task.ps1'
$statusPath = Join-Path $repoRoot 'windows-agent/check_agent_status.ps1'

foreach ($path in @($launcherPath, $installerPath, $uninstallerPath, $statusPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta el script de inicio: $path"
    }
}

$launcher = Get-Content -Raw -LiteralPath $launcherPath
$installer = Get-Content -Raw -LiteralPath $installerPath
$uninstaller = Get-Content -Raw -LiteralPath $uninstallerPath
$status = Get-Content -Raw -LiteralPath $statusPath

$launcherPatterns = @(
    '[switch]$Restart',
    'Get-CimInstance Win32_Process',
    'Stop-Process',
    'main.py',
    'IndexOf(',
    'Get-PipaLoopbackListenerProcessIds',
    'Request-PipaGracefulReload',
    '/internal/reload',
    'X-Pipa-Reload',
    'gracefulReloaded',
    'hasExactScript',
    '-B "{0}"',
    'hasKnownInterpreter',
    'linea de comandos exacta',
    'Stop-PipaProcessId -ProcessId ([int]$process.ProcessId) -Force',
    '127.0.0.1:8765',
    'sigue ocupado'
)
foreach ($pattern in $launcherPatterns) {
    if ($launcher.IndexOf($pattern, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El lanzador no contiene el control de recarga esperado: $pattern"
    }
}

if ($launcher.IndexOf('Stop-PipaLoopbackListener', [System.StringComparison]::Ordinal) -ge 0) {
    throw 'El lanzador no puede detener un proceso solo por escuchar en el puerto local.'
}

if ($installer.IndexOf("'-Restart'", [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El instalador no solicita la recarga del agente actualizado.'
}

foreach ($requiredPattern in @(
        "'/RL', 'LIMITED'",
        '-RunLevel Limited',
        '-WindowStyle Hidden',
        'expectedArguments',
        'exactAction',
        'currentUserPrincipal',
        '[StringComparison]::Ordinal',
        'Register-WithUserRun',
        'Register-WithStartupShortcut'
    )) {
    if ($installer.IndexOf($requiredPattern, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El instalador no conserva la politica de inicio seguro: $requiredPattern"
    }
}

if ($installer -match '(?i)(-RunLevel\s+Highest|/RL\s+HIGHEST|-Verb\s+RunAs)') {
    throw 'El instalador contiene una ruta de elevacion no permitida.'
}

foreach ($requiredUninstallerPattern in @(
        'Test-SafeTask',
        'Test-CurrentUserId',
        'schtasks.exe',
        '/Delete',
        'no se elimina por seguridad',
        '$previousErrorAction = $ErrorActionPreference',
        '$schtasksExitCode = $LASTEXITCODE'
    )) {
    if ($uninstaller.IndexOf($requiredUninstallerPattern, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El desinstalador no conserva la eliminacion segura de la tarea: $requiredUninstallerPattern"
    }
}

if ($status.IndexOf('$taskQueryFailed = $true', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El diagnostico no distingue una tarea ilegible de una tarea ausente.'
}
foreach ($requiredStatusPattern in @('currentUserSid', 'currentUserLeaf', 'Test-CurrentUserId', '$taskMissing', '$taskQueryFailed = $false', '$previousErrorAction = $ErrorActionPreference', '$schtasksExitCode = $LASTEXITCODE', 'file specified', 'archivo especificado')) {
    if ($status.IndexOf($requiredStatusPattern, [System.StringComparison]::Ordinal) -lt 0) {
        throw "El diagnostico no valida la identidad actual de forma exacta: $requiredStatusPattern"
    }
}

if ($installer.IndexOf('Test-CurrentUserPrincipal', [System.StringComparison]::Ordinal) -lt 0 -or
    $installer.IndexOf('currentUserLeaf', [System.StringComparison]::Ordinal) -lt 0 -or
    $installer.IndexOf('currentUserSid', [System.StringComparison]::Ordinal) -lt 0) {
    throw 'El instalador no acepta las representaciones equivalentes del usuario actual.'
}

if (($launcher + $installer + $uninstaller + $status) -match '(?i)(start_agent\.bat|\.cmd|\.vbs)') {
    throw 'Los scripts de inicio contienen un fallback de CMD/VBS no permitido.'
}

Write-Host 'Ciclo de actualizacion del agente OK: recarga exacta, oculta y sin CMD/VBS.' -ForegroundColor Green
