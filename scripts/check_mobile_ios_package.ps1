[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$confirmationContract = Join-Path $repoRoot 'scripts/check_mobile_confirmation_contract.py'
$requiredFiles = @(
    'mobile-ios/Package.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaMobileProtocol.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaKeychainIdentityStore.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaMobileSettingsStore.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaMobileTCPClient.swift',
    'mobile-ios/Sources/PipaMobileCore/PipaMobileDestinationPolicy.swift',
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

if (-not (Test-Path -LiteralPath $confirmationContract -PathType Leaf)) {
    throw 'Falta el verificador del contrato de confirmaciones móvil.'
}

$package = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Package.swift')
$protocol = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileProtocol.swift')
$keychain = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaKeychainIdentityStore.swift')
$settingsStore = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileSettingsStore.swift')
$tcp = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileTCPClient.swift')
$destinationPolicy = Get-Content -Raw (Join-Path $repoRoot 'mobile-ios/Sources/PipaMobileCore/PipaMobileDestinationPolicy.swift')
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
    @($settingsStore, 'PipaMobileSettings', 'PipaMobileSettingsStoring', 'validateForStorage', 'SecItemCopyMatching', 'SecItemUpdate', 'updateAttributes', 'kSecAttrSynchronizable', 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly'),
    @($destinationPolicy, 'PipaMobileDestinationPolicy', 'normalizePhone', 'normalizeSnowflake', 'first != "0"'),
    @($tcp, 'NWConnection', 'serverPublicKeyData', 'device_hello', 'catalog_request', 'PipaMobileCatalog', 'requestCatalogDetails', 'commands.count <= 64', 'parseCapabilities', 'capabilityGroups', 'booleanCapabilityFields', 'isCapabilityValue', 'isAllowedHost', 'first != "0"', 'first == 192', 'containsProtocolControl', 'maxArgumentsBytes', 'requestInFlight', 'requestInProgress', 'asyncAfter', 'connectionTimeout', 'ioTimeout', 'receiveBuffer'),
    @($viewModel, 'PipaMobileTCPClient', 'PipaKeychainIdentityStore', 'PipaMobileSettingsStoring', 'PipaMobileSettingsStore', 'PipaMobileIntegration', 'PipaMobileCommandParameter', 'guild_id', 'parameters', 'integrationCapabilities', 'requestCatalogDetails', 'pendingConfirmation', 'resolveConfirmation', 'prepareIdentity', 'identityFingerprint', 'serverFingerprint', 'serverFingerprintVerified', 'markServerFingerprintVerified', 'invalidateServerFingerprintVerification', 'useCommand', 'useCommandText', 'updateVoiceDraft', 'forgetConnectionSettings', 'sendStructuredCommand', 'operationTask', 'requestTask', 'requestInProgress', 'sessionGeneration', 'connectInProgress', 'Task.isCancelled', 'await newClient.disconnect()', 'closeAfterOperationFailure', 'requiresConfirmation == (safety == "unsafe")', 'parseCatalogCommands', 'Set(parsed.map(\.id)).count == parsed.count', 'isSafeConfirmationSummary', 'guard let expected = deviceConfirmationSummaries[toolName] else', 'whatsapp_phone_open', 'La respuesta del agente no es válida.'),
    @($commandEditor, 'placeholders', 'rendered(with values:', 'toolArguments(with values:', 'PipaMobileDestinationPolicy', 'normalizePhone', 'normalizeSnowflake', 'isSafeMessageText', '4000', 'Control', 'privacySensitive', 'Preparar en el editor', 'Enviar acción estructurada', 'without executing it'),
    @($appleMusic, 'MusicCatalogSearchRequest', 'MusicAuthorization', 'SystemMusicPlayer', 'search(term:', 'play(result:', 'skipToNextEntry', 'skipToPreviousEntry', 'player.stop()', 'previousTrack()', 'stopPlayback()', 'PipaMobileTextPolicy'),
    @($localIntegrationLinks, 'PipaMobileLocalIntegrationLinks', 'PipaMobileDestinationPolicy', 'wa.me', 'discord.com', 'isSafeMessageText', 'normalizeSnowflake', 'human'),
    @($speech, '#if os(iOS)', 'AVAudioEngine', 'SFSpeechRecognizer', 'requestRecordPermission', 'supportsOnDeviceRecognition', 'requiresOnDeviceRecognition', 'PipaMobileSpeechRecognizer', 'operationGeneration', 'generation:', 'invalidate: true', 'bounded(text)'),
    @($view, 'PipaMobileRootView', 'LocalIntegrationAction', 'Equatable', 'pendingLocalIntegrationAction', '.confirmationDialog', 'performPendingLocalIntegrationAction', 'scenePhase', 'onChange', 'commandToEdit', '.sheet(item:', 'command.placeholders', 'integrationSection', 'integrationCapabilities', 'localAppleMusic', 'Apple Music en este iPhone', 'Anterior', 'Detener', 'privacySensitive', 'Disponible', 'No disponible', 'Preparar identidad', 'Fingerprint:', 'Fingerprint del agente:', 'He comparado el fingerprint', 'Fingerprint verificado', 'Confirmar acción', 'Rechazar', 'Aceptar', 'Usar', 'PipaMobileSpeechRecognizer', 'Dictar comando', 'Parar dictado', 'updateVoiceDraft', 'speechRecognizer.cancel()', 'speechRecognizer.isListening', 'Borrar configuración guardada'),
    @($app, '@main', 'PipaMobileRootView', 'WindowGroup'),
    @($appInfo, 'CFBundleDisplayName', 'LSRequiresIPhoneOS', 'NSAppleMusicUsageDescription', 'NSLocalNetworkUsageDescription', 'NSMicrophoneUsageDescription', 'NSSpeechRecognitionUsageDescription'),
    @($xcodeProject, 'PBXProject', 'PBXNativeTarget', 'PipaMobileApp.swift', 'PipaMobileUI', 'XCLocalSwiftPackageReference', 'relativePath = ..', 'INFOPLIST_FILE = ../App/Info.plist', 'IPHONEOS_DEPLOYMENT_TARGET = 16.0'),
    @($xcodeScheme, 'BlueprintName = "PipaMobile"', 'BuildableName = "PipaMobile.app"', 'container:PipaMobile.xcodeproj'),
    @($infoPlist, 'CFBundleDisplayName', 'LSRequiresIPhoneOS', 'NSAppleMusicUsageDescription', 'NSLocalNetworkUsageDescription', 'NSMicrophoneUsageDescription', 'NSSpeechRecognitionUsageDescription', 'red local'),
    @($coreTests, 'testRecordLayerEncryptsAuthenticatesAndRejectsReplay', 'testRecordLayerMatchesTheSharedPythonVector', 'testTCPClientRejectsInvalidTextAndOversizedArgumentsBeforeTransport', 'testMobileEndpointRejectsPublicAndWildcardHosts', '192.168.001.020', 'testMobileTextPolicyRejectsProtocolAndBidirectionalControls', 'testDestinationPolicyUsesCanonicalPhoneAndDiscordIDs', '01234567', 'testMobileSettingsRejectUnsafePersistedValuesBeforeTransport'),
    @($uiTests, 'testConnectionRequiresEphemeralFingerprintAcknowledgement', 'testSavedSettingsNeverCountAsFingerprintAcknowledgement', 'testCatalogCommandEditorRendersBoundedArgumentsWithoutSending', 'testCatalogRejectsDuplicateAndOversizedCommandLists', 'testStructuredCatalogCommandAcceptsMessageLineFeedsAndTypedArguments', 'testStructuredCatalogCommandRejectsMalformedParameterMetadata', 'testVoiceDraftOnlyUpdatesTheEditorWithoutSending', 'testVoiceDraftRejectsControlCharactersAndOversizedInput', 'testCatalogRejectsBidirectionalFormattingControls', 'testIntegrationCapabilitiesShowOnlyCoarseManualActionStatus', 'testLocalAppleMusicControllerStartsWithoutAuthorizationOrTransport'),
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

$python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -eq $python) {
    throw 'No se encontró Python para verificar el contrato de confirmaciones móvil.'
}
$contractOutput = @(& $python.Source $confirmationContract 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "El contrato de confirmaciones móvil falló: $($contractOutput -join ' ')"
}
Write-Host ($contractOutput -join "`n")

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
