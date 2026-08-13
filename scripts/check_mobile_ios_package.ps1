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
    'mobile-ios/Sources/PipaMobileUI/PipaMobileAppleMusicController.swift',
    'mobile-ios/Sources/PipaMobileUI/PipaMobileLocalIntegrationLinks.swift',
    'mobile-ios/Sources/PipaMobileUI/PipaMobileSpeechRecognizer.swift',
    'mobile-ios/Sources/PipaMobileUI/PipaMobileRootView.swift',
    'mobile-ios/App/PipaMobileApp.swift',
    'mobile-ios/App/Info.plist',
    'mobile-ios/App/Info.plist.example',
    'mobile-ios/PipaMobileApp/PipaMobile.xcodeproj/project.pbxproj',
    'mobile-ios/PipaMobileApp/PipaMobile.xcodeproj/xcshareddata/xcschemes/PipaMobile.xcscheme',
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
$appleMusic = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileAppleMusicController.swift')
$localIntegrationLinks = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileLocalIntegrationLinks.swift')
$speech = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileSpeechRecognizer.swift')
$view = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileUI/PipaMobileRootView.swift')
$app = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/App/PipaMobileApp.swift')
$appInfo = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/App/Info.plist')
$xcodeProject = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/PipaMobileApp/PipaMobile.xcodeproj/project.pbxproj')
$xcodeScheme = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/PipaMobileApp/PipaMobile.xcodeproj/xcshareddata/xcschemes/PipaMobile.xcscheme')
$infoPlist = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/App/Info.plist.example')
$arrivalChecklist = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/ARRIVAL_CHECKLIST.md')
$mobileProtocol = Get-Content -Raw (Join-Path $repoRoot 'MOBILE_PROTOCOL.md')
$coreTests = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Tests/PipaMobileCoreTests/PipaMobileProtocolTests.swift')
$uiTests = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Tests/PipaMobileUITests/PipaMobileUITests.swift')
$vector = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Tests/Fixtures/mobile_record_v2.json')
$ignore = Get-Content -Raw (Join-Path $repoRoot '.gitignore')

$requiredPatterns = @(
    @($package, '.iOS(.v16)', '.macOS(.v13)', 'PipaMobileCore', 'PipaMobileUI', 'PipaMobileCoreTests', 'PipaMobileUITests'),
    @($protocol, 'Curve25519.Signing', 'ChaChaPoly', 'HKDF<SHA256>.deriveKey', 'sharedSecretData', 'maxFrameBytes', 'publicKeyDigest(forPublicKeyData', 'encodeBase64URL(data) == value', 'sequence < UInt64.max', 'closed = true', 'PipaMobileTextPolicy', 'containsDisplayControl', 'isSafeMessageText'),
    @($keychain, 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly', 'kSecClassGenericPassword'),
    @($settingsStore, 'PipaMobileSettings', 'PipaMobileSettingsStoring', 'SecItemCopyMatching', 'SecItemUpdate', 'updateAttributes', 'kSecAttrSynchronizable', 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly'),
    @($tcp, 'NWConnection', 'serverPublicKeyData', 'device_hello', 'catalog_request', 'PipaMobileCatalog', 'requestCatalogDetails', 'parseCapabilities', 'capabilityGroups', 'booleanCapabilityFields', 'isCapabilityValue', 'isAllowedHost', 'first == 192', 'containsProtocolControl', 'maxArgumentsBytes', 'requestInFlight', 'requestInProgress', 'asyncAfter', 'connectionTimeout', 'ioTimeout', 'receiveBuffer'),
    @($viewModel, 'PipaMobileTCPClient', 'PipaKeychainIdentityStore', 'PipaMobileSettingsStoring', 'PipaMobileSettingsStore', 'PipaMobileIntegration', 'PipaMobileCommandParameter', 'guild_id', 'parameters', 'integrationCapabilities', 'requestCatalogDetails', 'pendingConfirmation', 'resolveConfirmation', 'prepareIdentity', 'identityFingerprint', 'serverFingerprint', 'serverFingerprintVerified', 'markServerFingerprintVerified', 'invalidateServerFingerprintVerification', 'useCommand', 'useCommandText', 'updateVoiceDraft', 'forgetConnectionSettings', 'sendStructuredCommand', 'operationTask', 'requestTask', 'requestInProgress', 'sessionGeneration', 'connectInProgress', 'Task.isCancelled', 'await newClient.disconnect()', 'closeAfterOperationFailure', 'requiresConfirmation == (safety == "unsafe")', 'parsedCatalog.count == catalog.commands.count', 'isSafeConfirmationSummary', 'whatsapp_phone_open', 'La respuesta del agente no es válida.'),
    @($commandEditor, 'placeholders', 'rendered(with values:', 'toolArguments(with values:', 'isSafeMessageText', '4000', 'Control', 'Preparar en el editor', 'Enviar acción estructurada', 'without executing it'),
    @($appleMusic, 'MusicCatalogSearchRequest', 'MusicAuthorization', 'SystemMusicPlayer', 'search(term:', 'play(result:', 'skipToNextEntry', 'skipToPreviousEntry', 'player.stop()', 'previousTrack()', 'stopPlayback()', 'PipaMobileTextPolicy'),
    @($localIntegrationLinks, 'PipaMobileLocalIntegrationLinks', 'wa.me', 'discord.com', 'isSafeMessageText', 'normalizeSnowflake', 'human'),
    @($speech, '#if os(iOS)', 'AVAudioEngine', 'SFSpeechRecognizer', 'requestRecordPermission', 'supportsOnDeviceRecognition', 'requiresOnDeviceRecognition', 'PipaMobileSpeechRecognizer', 'operationGeneration', 'generation:', 'invalidate: true', 'bounded(text)'),
    @($view, 'PipaMobileRootView', 'scenePhase', 'onChange', 'commandToEdit', '.sheet(item:', 'command.placeholders', 'integrationSection', 'integrationCapabilities', 'localAppleMusic', 'Apple Music en este iPhone', 'Anterior', 'Detener', 'privacySensitive', 'Disponible', 'No disponible', 'Preparar identidad', 'Fingerprint:', 'Fingerprint del agente:', 'He comparado el fingerprint', 'Fingerprint verificado', 'Confirmar acción', 'Rechazar', 'Aceptar', 'Usar', 'PipaMobileSpeechRecognizer', 'Dictar comando', 'Parar dictado', 'updateVoiceDraft', 'speechRecognizer.cancel()', 'speechRecognizer.isListening', 'Borrar configuración guardada'),
    @($app, '@main', 'PipaMobileRootView', 'WindowGroup'),
    @($appInfo, 'CFBundleDisplayName', 'LSRequiresIPhoneOS', 'NSAppleMusicUsageDescription', 'NSLocalNetworkUsageDescription', 'NSMicrophoneUsageDescription', 'NSSpeechRecognitionUsageDescription'),
    @($xcodeProject, 'PBXProject', 'PBXNativeTarget', 'PipaMobileApp.swift', 'PipaMobileUI', 'XCLocalSwiftPackageReference', 'relativePath = ..', 'INFOPLIST_FILE = ../App/Info.plist', 'IPHONEOS_DEPLOYMENT_TARGET = 16.0'),
    @($xcodeScheme, 'BlueprintName = "PipaMobile"', 'BuildableName = "PipaMobile.app"', 'container:PipaMobile.xcodeproj'),
    @($infoPlist, 'CFBundleDisplayName', 'LSRequiresIPhoneOS', 'NSAppleMusicUsageDescription', 'NSLocalNetworkUsageDescription', 'NSMicrophoneUsageDescription', 'NSSpeechRecognitionUsageDescription', 'red local'),
    @($coreTests, 'testRecordLayerEncryptsAuthenticatesAndRejectsReplay', 'testRecordLayerMatchesTheSharedPythonVector', 'testTCPClientRejectsInvalidTextAndOversizedArgumentsBeforeTransport', 'testMobileTextPolicyRejectsProtocolAndBidirectionalControls'),
    @($uiTests, 'testConnectionRequiresEphemeralFingerprintAcknowledgement', 'testSavedSettingsNeverCountAsFingerprintAcknowledgement', 'testCatalogCommandEditorRendersBoundedArgumentsWithoutSending', 'testStructuredCatalogCommandAcceptsMessageLineFeedsAndTypedArguments', 'testStructuredCatalogCommandRejectsMalformedParameterMetadata', 'testVoiceDraftOnlyUpdatesTheEditorWithoutSending', 'testVoiceDraftRejectsControlCharactersAndOversizedInput', 'testCatalogRejectsBidirectionalFormattingControls', 'testIntegrationCapabilitiesShowOnlyCoarseManualActionStatus', 'testLocalAppleMusicControllerStartsWithoutAuthorizationOrTransport'),
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

if ($appInfo -ne $infoPlist) {
    throw 'App/Info.plist y App/Info.plist.example deben mantenerse sincronizados.'
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
        $appleMusic.Contains($pattern) -or $localIntegrationLinks.Contains($pattern) -or $speech.Contains($pattern) -or $view.Contains($pattern) -or $app.Contains($pattern) -or
        $appInfo.Contains($pattern) -or $xcodeProject.Contains($pattern) -or $xcodeScheme.Contains($pattern) -or
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
