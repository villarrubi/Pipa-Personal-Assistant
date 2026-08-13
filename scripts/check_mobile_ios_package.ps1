[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$requiredFiles = @(
    'mobile-ios/Package.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaMobileProtocol.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaKeychainIdentityStore.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaMobileSettingsStore.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaMobileTCPClient.swift',
    'mobile-ios/Sources/PipaMobileUI/PipaMobileViewModel.swift',
    'mobile-ios/Sources/PipaMobileUI/PipaMobileCommandEditor.swift',
    'mobile-ios/Sources/PipaMobileUI/PipaMobileSpeechRecognizer.swift',
    'mobile-ios/Sources/PipaMobileUI/PipaMobileRootView.swift',
    'mobile-ios/App/PipaMobileApp.swift',
    'mobile-ios/App/Info.plist.example',
    'mobile-ios/ARRIVAL_CHECKLIST.md',
    'MOBILE_PROTOCOL.md',
    'mobile-ios/Tests/PipaMobileCoreTests/PipaMobileProtocolTests.swift',
    'mobile-ios/Tests/Fixtures/mobile_record_v2.json',
    'mobile-ios/Tests/PipaMobileUITests/PipaMobileUITests.swift'
)

foreach ($relativePath in $requiredFiles) {
    $path = Join-Path $repoRoot ($relativePath -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta el archivo del paquete iOS: $relativePath"
    }
}

$package = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Package.swift')
$protocol = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileProtocol.swift')
$keychain = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaKeychainIdentityStore.swift')
$settingsStore = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileSettingsStore.swift')
$tcp = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileTCPClient.swift')
$viewModel = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileViewModel.swift')
$commandEditor = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileCommandEditor.swift')
$speech = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileSpeechRecognizer.swift')
$view = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileRootView.swift')
$app = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/App/PipaMobileApp.swift')
$infoPlist = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/App/Info.plist.example')
$arrivalChecklist = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/ARRIVAL_CHECKLIST.md')
$mobileProtocol = Get-Content -Raw (Join-Path $repoRoot 'MOBILE_PROTOCOL.md')
$coreTests = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Tests/PipaMobileCoreTests/PipaMobileProtocolTests.swift')
$uiTests = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Tests/PipaMobileUITests/PipaMobileUITests.swift')
$vector = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Tests/Fixtures/mobile_record_v2.json')
$ignore = Get-Content -Raw (Join-Path $repoRoot '.gitignore')

$requiredPatterns = @(
    @($package, '.iOS(.v16)', '.macOS(.v13)', 'PipaMobileCore', 'PipaMobileUI', 'PipaMobileCoreTests', 'PipaMobileUITests'),
    @($protocol, 'Curve25519.Signing', 'ChaChaPoly', 'hkdfDerivedSymmetricKey', 'sharedSecretData', 'maxFrameBytes', 'publicKeyDigest(forPublicKeyData', 'encodeBase64URL(data) == value', 'sequence < UInt64.max', 'closed = true', 'PipaMobileTextPolicy', 'containsDisplayControl'),
    @($keychain, 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly', 'kSecClassGenericPassword'),
    @($settingsStore, 'PipaMobileSettings', 'PipaMobileSettingsStoring', 'SecItemCopyMatching', 'SecItemUpdate', 'updateAttributes', 'kSecAttrSynchronizable', 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly'),
    @($tcp, 'NWConnection', 'serverPublicKeyData', 'device_hello', 'catalog_request', 'PipaMobileCatalog', 'requestCatalogDetails', 'parseCapabilities', 'capabilityGroups', 'booleanCapabilityFields', 'isCapabilityValue', 'isAllowedHost', 'first == 192', 'containsProtocolControl', 'maxArgumentsBytes', 'requestInFlight', 'requestInProgress', 'asyncAfter', 'connectionTimeout', 'ioTimeout', 'receiveBuffer'),
    @($viewModel, 'PipaMobileTCPClient', 'PipaKeychainIdentityStore', 'PipaMobileSettingsStoring', 'PipaMobileSettingsStore', 'PipaMobileIntegration', 'integrationCapabilities', 'requestCatalogDetails', 'pendingConfirmation', 'resolveConfirmation', 'prepareIdentity', 'identityFingerprint', 'serverFingerprint', 'serverFingerprintVerified', 'markServerFingerprintVerified', 'invalidateServerFingerprintVerification', 'useCommand', 'useCommandText', 'updateVoiceDraft', 'forgetConnectionSettings', 'operationTask', 'requestTask', 'requestInProgress', 'sessionGeneration', 'connectInProgress', 'Task.isCancelled', 'await newClient.disconnect()', 'closeAfterOperationFailure', 'requiresConfirmation == (safety == "unsafe")', 'parsedCatalog.count == catalog.commands.count', 'isSafeConfirmationSummary', 'La respuesta del agente no es válida.'),
    @($commandEditor, 'placeholders', 'rendered(with values:', '4000', 'Control', 'Preparar en el editor', 'without executing it'),
    @($speech, '#if os(iOS)', 'AVAudioEngine', 'SFSpeechRecognizer', 'requestRecordPermission', 'supportsOnDeviceRecognition', 'requiresOnDeviceRecognition', 'PipaMobileSpeechRecognizer', 'bounded(text)'),
    @($view, 'PipaMobileRootView', 'scenePhase', 'onChange', 'commandToEdit', '.sheet(item:', 'command.placeholders', 'integrationSection', 'integrationCapabilities', 'Disponible', 'No disponible', 'Preparar identidad', 'Fingerprint:', 'Fingerprint del agente:', 'He comparado el fingerprint', 'Fingerprint verificado', 'Confirmar acción', 'Rechazar', 'Aceptar', 'Usar', 'PipaMobileSpeechRecognizer', 'Dictar comando', 'Parar dictado', 'updateVoiceDraft', 'speechRecognizer.cancel()', 'speechRecognizer.isListening', 'Borrar configuración guardada'),
    @($app, '@main', 'PipaMobileRootView', 'WindowGroup'),
    @($infoPlist, 'CFBundleDisplayName', 'LSRequiresIPhoneOS', 'NSLocalNetworkUsageDescription', 'NSMicrophoneUsageDescription', 'NSSpeechRecognitionUsageDescription', 'red local'),
    @($coreTests, 'testRecordLayerEncryptsAuthenticatesAndRejectsReplay', 'testRecordLayerMatchesTheSharedPythonVector', 'testTCPClientRejectsInvalidTextAndOversizedArgumentsBeforeTransport', 'testMobileTextPolicyRejectsProtocolAndBidirectionalControls'),
    @($uiTests, 'testConnectionRequiresEphemeralFingerprintAcknowledgement', 'testSavedSettingsNeverCountAsFingerprintAcknowledgement', 'testCatalogCommandEditorRendersBoundedArgumentsWithoutSending', 'testVoiceDraftOnlyUpdatesTheEditorWithoutSending', 'testVoiceDraftRejectsControlCharactersAndOversizedInput', 'testCatalogRejectsBidirectionalFormattingControls', 'testIntegrationCapabilitiesShowOnlyCoarseManualActionStatus'),
    @($arrivalChecklist, 'python .\windows-agent\trusted_unlock_admin.py pair-mobile', 'FINGERPRINT_COMPARADO'),
    @($mobileProtocol, 'python .\windows-agent\trusted_unlock_admin.py pair-mobile', 'python .\windows-agent\trusted_unlock_admin.py list-mobile', 'python .\windows-agent\trusted_unlock_admin.py revoke-mobile'),
    @($vector, 'vector-mobile', 'shared_secret', 'ciphertext_and_tag'),
    @($ignore, 'mobile-ios/.build/', 'mobile-ios/.swiftpm/', 'xcuserdata', '*.xcuserstate')
)

foreach ($check in $requiredPatterns) {
    $content = $check[0]
    foreach ($pattern in $check[1..($check.Count - 1)]) {
        if ($content.IndexOf($pattern, [System.StringComparison]::Ordinal) -lt 0) {
            throw "El paquete iOS no contiene el control esperado: $pattern"
        }
    }
}

$forbiddenPatterns = @(
    'public let privateKey',
    'public var privateKey',
    'public init(identityID: String, privateKey',
    'print(',
    'NSLog(',
    'UserDefaults',
    'PIPA_SERIAL_PORT'
)

foreach ($pattern in $forbiddenPatterns) {
    if ($protocol.Contains($pattern) -or $keychain.Contains($pattern) -or $tcp.Contains($pattern) -or
        $settingsStore.Contains($pattern) -or $viewModel.Contains($pattern) -or
        $speech.Contains($pattern) -or $view.Contains($pattern) -or $app.Contains($pattern) -or
        $arrivalChecklist.Contains($pattern) -or $mobileProtocol.Contains($pattern)) {
        throw "El paquete iOS contiene un patrón no permitido: $pattern"
    }
}

$swift = Get-Command swift -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -ne $swift) {
    $output = @(& $swift.Source 'test' '--package-path' (Join-Path $repoRoot 'mobile-ios') 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Las pruebas Swift fallaron: $($output -join ' ')"
    }
    Write-Host 'Pruebas Swift OK: swift test completado.'
} else {
    Write-Host 'INFO: swift no esta instalado; se omite la compilacion Swift en este equipo.'
}

Write-Host 'Paquete iOS estructural OK: contrato, Keychain, TCP v2 y exclusiones revisados.'
