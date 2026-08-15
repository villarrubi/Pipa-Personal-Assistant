[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$patternsPath = Join-Path $PSScriptRoot 'security_patterns.ps1'
if (-not (Test-Path -LiteralPath $patternsPath -PathType Leaf)) {
    throw "Falta la fuente común de patrones de seguridad: $patternsPath"
}
. $patternsPath

$reviewedFiles = @(git -C $repoRoot ls-files --cached --others --exclude-standard)
$violations = [System.Collections.Generic.List[string]]::new()

$forbiddenPathPattern = (
    '(^|/)(build|build-ci|__pycache__|\.venv|venv|out|bin|obj|dist|\.pio|\.platformio|\.platformio-preflight)(/|$)|' +
    '(^|/)windows-agent/config/apps\.json$|' +
    '(^|/)firmware/include/pipa_device_config\.local\.h$|' +
    '(^|/)secure_agent_identity\.json$'
)
foreach ($path in $reviewedFiles) {
    if ($path -match $forbiddenPathPattern) {
        $violations.Add("Archivo generado o local rastreado: $path")
    }
    $absolutePath = Join-Path $repoRoot $path
    if ((Test-Path -LiteralPath $absolutePath -PathType Leaf) -and
        (Get-Item -LiteralPath $absolutePath).Length -gt 5MB) {
        $violations.Add("Archivo rastreado mayor de 5 MiB: $path")
    }
}

$windowsUserPath = 'C:' + '\\Users\\'
$portableUserPath = 'C:' + '/Users/'
$sensitiveContentPattern = [regex]::Escape($windowsUserPath) + '|' +
    [regex]::Escape($portableUserPath) + '|' +
    (Get-PipaWorkingTreeSecretPattern)
foreach ($path in $reviewedFiles) {
    $absolutePath = Join-Path $repoRoot $path
    if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
        (Get-Item -LiteralPath $absolutePath).Length -gt 5MB) {
        continue
    }
    $matches = @(Select-String -LiteralPath $absolutePath -Pattern $sensitiveContentPattern)
    foreach ($match in $matches) {
        $violations.Add("Contenido potencialmente sensible: ${path}:$($match.LineNumber)")
    }
}

# Verify the ignore policy itself with hypothetical paths. This catches a
# weakened pattern before a local config, recording, capture or build can be
# staged accidentally. --no-index makes the check independent of whether a
# fixture happens to exist on disk.
$ignoreFixtures = @(
    '.env',
    '.env.local',
    'windows-agent/config/apps.json',
    'windows-agent/config/contacts.local.json',
    'windows-agent/config/apps.private.json',
    'secure_agent_identity.json',
    'windows-agent/config/secure_agent_identity.json',
    'firmware/include/pipa_device_config.local.h',
    'firmware/.pio/build/waveshare-185c/firmware.bin',
    'firmware/.platformio/packages/framework-arduinoespressif32/package.txt',
    '.platformio-preflight/packages/platformio/package.json',
    'windows-agent/__pycache__/main.cpython-312.pyc',
    'logs/agent.log',
    'captures/logonui.png',
    'recordings/voice.wav',
    'exports/browser.har',
    'device-private.key',
    'device-certificate.crt',
    'desktop-session.rdp',
    'session-token.txt',
    '.aws/credentials',
    '.config/gcloud/application_default_credentials.json',
    '.npmrc',
    '.pypirc',
    'mobile-ios/App/Pipa.mobileprovision',
    'mobile-ios/App/signing.p12',
    'trusted-unlock/build/Release/PipaTrustedUnlock.dll'
)
foreach ($fixture in $ignoreFixtures) {
    git -C $repoRoot check-ignore --no-index --quiet -- $fixture
    if ($LASTEXITCODE -ne 0) {
        $violations.Add("La politica .gitignore no cubre la ruta sensible de prueba: $fixture")
    }
}

# Broad ignore rules such as *token* and *credential* can hide real source
# files from both Git and this scanner. Keep representative source and docs
# visible so future security work cannot be omitted silently.
$visibleSourceFixtures = @(
    'backend/pipa_core/token_policy.py',
    'windows-agent/credential_rotation.py',
    'windows-agent/tests/test_token_policy.py',
    'docs/secret_handling.md',
    'trusted-unlock/src/CredentialAudit.cpp'
)
foreach ($fixture in $visibleSourceFixtures) {
    git -C $repoRoot check-ignore --no-index --quiet -- $fixture
    if ($LASTEXITCODE -eq 0) {
        $violations.Add("La politica .gitignore ocultaria codigo o documentacion legitima: $fixture")
    }
}

$safeDeviceConfig = Join-Path $repoRoot 'firmware/include/pipa_device_config.h'
if (Test-Path -LiteralPath $safeDeviceConfig -PathType Leaf) {
    $configText = Get-Content -LiteralPath $safeDeviceConfig -Raw
    if ($configText -notmatch '#define PIPA_WIFI_SSID ""' -or
        $configText -notmatch '#define PIPA_WIFI_PASSWORD ""' -or
        $configText -notmatch '#define PIPA_PC_MAC "00:00:00:00:00:00"') {
        $violations.Add('La configuracion de firmware rastreada no contiene valores locales seguros.')
    }
}

if ($violations.Count -gt 0) {
    $violations | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Higiene Git OK: $($reviewedFiles.Count) archivos publicables revisados." -ForegroundColor Green
