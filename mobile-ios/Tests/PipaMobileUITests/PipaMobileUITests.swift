import XCTest

@testable import PipaMobileCore
@testable import PipaMobileUI

@available(iOS 16.0, macOS 13.0, *)
@MainActor
final class PipaMobileUITests: XCTestCase {
    private final class MemorySettingsStore: PipaMobileSettingsStoring {
        var settings: PipaMobileSettings?
        var deleteCalled = false

        func load() throws -> PipaMobileSettings? { settings }

        func save(_ settings: PipaMobileSettings) throws {
            self.settings = settings
        }

        func delete() throws {
            settings = nil
            deleteCalled = true
        }
    }

    func testViewModelStartsDisconnectedAndDoesNotInventConfiguration() {
        let model = PipaMobileViewModel()

        XCTAssertEqual(model.connectionState, .disconnected)
        XCTAssertFalse(model.isConnected)
        XCTAssertFalse(model.requestInProgress)
        XCTAssertTrue(model.commands.isEmpty)
        XCTAssertTrue(model.serverPublicKey.isEmpty)
    }

    func testIntegrationCapabilitiesShowOnlyCoarseManualActionStatus() {
        let music = PipaMobileIntegration(
            id: "apple_music",
            payload: [
                "available": true,
                "app_configured": false,
                "requires_manual_selection": true,
                "media_control": true,
            ]
        )
        let league = PipaMobileIntegration(
            id: "league",
            payload: [
                "available": true,
                "client_ready": false,
                "requires_manual_accept": true,
            ]
        )

        XCTAssertEqual(music?.title, "Apple Music")
        XCTAssertEqual(
            music?.detail,
            "Apple Music Web disponible; busca y selecciona la pista y controla reproducción/pausa manualmente."
        )
        XCTAssertFalse(music?.appConfigured ?? true)
        XCTAssertEqual(
            league?.detail,
            "El cliente está configurado, pero no está listo ahora; aceptar la partida será manual."
        )
        XCTAssertNil(PipaMobileIntegration(id: "unknown", payload: ["available": true]))
    }

    func testLocalAppleMusicControllerStartsWithoutAuthorizationOrTransport() {
        let controller = PipaMobileAppleMusicController()

        XCTAssertFalse(controller.isAuthorized)
        XCTAssertFalse(controller.isPlaying)
        XCTAssertFalse(controller.requestInProgress)
        XCTAssertTrue(controller.currentTrack.isEmpty)
#if os(iOS)
        XCTAssertTrue(controller.isNativePlaybackAvailable)
#else
        XCTAssertFalse(controller.isNativePlaybackAvailable)
#endif
    }

    func testLocalAppleMusicRejectsUnsafeQueryBeforeAuthorizationOrTransport() {
        let controller = PipaMobileAppleMusicController()

        controller.search(term: "Pipa\u{202E}Music")

        XCTAssertFalse(controller.isAuthorized)
        XCTAssertFalse(controller.requestInProgress)
        XCTAssertTrue(controller.searchResults.isEmpty)
        XCTAssertEqual(controller.statusMessage, "Escribe una búsqueda musical válida y acotada.")
    }

    func testLocalWakeOnLanStartsIdleAndDoesNotRequireAgentTransport() {
        let controller = PipaMobileWakeOnLanController()

        XCTAssertFalse(controller.requestInProgress)
        XCTAssertTrue(controller.statusMessage.contains("red local"))
        XCTAssertFalse(controller.validate(mac: "not-a-mac"))
        XCTAssertEqual(controller.statusMessage, "Introduce una MAC unicast válida.")
        XCTAssertNotNil(PipaMobileWakeOnLan.magicPacket(for: "AA:BB:CC:DD:EE:F0"))
    }

    func testLocalWhatsAppLinkPreparesMessageWithoutChangingItsContents() throws {
        let url = try XCTUnwrap(
            PipaMobileLocalIntegrationLinks.whatsappComposeURL(
                phone: "+34 600-123-456",
                message: "Hola\nMamá"
            )
        )

        XCTAssertEqual(url.scheme, "https")
        XCTAssertEqual(url.host, "wa.me")
        XCTAssertEqual(url.path, "/34600123456")
        let queryItems = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems)
        XCTAssertEqual(queryItems.first?.name, "text")
        XCTAssertEqual(queryItems.first?.value, "Hola\nMamá")
    }

    func testLocalWebSearchLinkIsFixedAndEncodesTheQuery() throws {
        let url = try XCTUnwrap(
            PipaMobileLocalIntegrationLinks.webSearchURL(query: "documentación de Pipα")
        )

        XCTAssertEqual(url.scheme, "https")
        XCTAssertEqual(url.host, "www.google.com")
        XCTAssertEqual(url.path, "/search")
        let queryItems = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems)
        XCTAssertEqual(queryItems.first?.name, "q")
        XCTAssertEqual(queryItems.first?.value, "documentación de Pipα")
    }

    func testLocalWebSearchLinkRejectsEmptyUnsafeOrOversizedQueries() {
        XCTAssertNil(PipaMobileLocalIntegrationLinks.webSearchURL(query: "   "))
        XCTAssertNil(PipaMobileLocalIntegrationLinks.webSearchURL(query: "Pipa\u{202E}codex"))
        XCTAssertNil(PipaMobileLocalIntegrationLinks.webSearchURL(query: String(repeating: "a", count: 201)))
    }

    func testLocalWhatsAppLinkRejectsInvalidOrUnsafeInput() {
        XCTAssertNil(
            PipaMobileLocalIntegrationLinks.whatsappComposeURL(
                phone: "not-a-phone",
                message: "Hola"
            )
        )
        XCTAssertNil(
            PipaMobileLocalIntegrationLinks.whatsappComposeURL(
                phone: "+34 600 123 456",
                message: "Hola\u{202E}Mamá"
            )
        )
        XCTAssertNil(
            PipaMobileLocalIntegrationLinks.whatsappComposeURL(
                phone: "+01234567",
                message: "Hola"
            )
        )
    }

    func testLocalDiscordLinkUsesDMByDefaultAndServerWhenProvided() throws {
        let directMessage = try XCTUnwrap(
            PipaMobileLocalIntegrationLinks.discordChannelURL(channelID: "12345678901234567")
        )
        XCTAssertEqual(directMessage.absoluteString, "https://discord.com/channels/@me/12345678901234567")

        let serverChannel = try XCTUnwrap(
            PipaMobileLocalIntegrationLinks.discordChannelURL(
                channelID: "12345678901234567",
                guildID: "98765432109876543"
            )
        )
        XCTAssertEqual(serverChannel.absoluteString, "https://discord.com/channels/98765432109876543/12345678901234567")
    }

    func testLocalDiscordLinkRejectsInvalidIdentifiers() {
        XCTAssertNil(PipaMobileLocalIntegrationLinks.discordChannelURL(channelID: "not-an-id"))
        XCTAssertNil(
            PipaMobileLocalIntegrationLinks.discordChannelURL(
                channelID: "12345678901234567",
                guildID: "not-a-server"
            )
        )
        XCTAssertNil(
            PipaMobileLocalIntegrationLinks.discordChannelURL(
                channelID: "012345678901234567",
                guildID: nil
            )
        )
    }

    func testConfirmationSummaryRejectsArgumentsAndAllowsFixedLabels() {
        XCTAssertTrue(
            PipaMobileViewModel.isSafeConfirmationSummary(
                toolName: "whatsapp_compose",
                summary: "Preparar un mensaje de WhatsApp; el envío será manual."
            )
        )
        XCTAssertTrue(
            PipaMobileViewModel.isSafeConfirmationSummary(
                toolName: "discord_call_channel",
                summary: "Preparar una llamada de Discord; el inicio será manual."
            )
        )
        XCTAssertTrue(
            PipaMobileViewModel.isSafeConfirmationSummary(
                toolName: "whatsapp_phone_open",
                summary: "Abrir un chat de WhatsApp."
            )
        )
        XCTAssertFalse(
            PipaMobileViewModel.isSafeConfirmationSummary(
                toolName: "whatsapp_compose",
                summary: "Preparar WhatsApp para +34 600 123 456: mensaje secreto"
            )
        )
        XCTAssertFalse(
            PipaMobileViewModel.isSafeConfirmationSummary(
                toolName: "future_external_tool",
                summary: "Confirmar acción externa."
            )
        )
    }

    func testCatalogCommandOnlyPrefillsTheEditor() throws {
        let model = PipaMobileViewModel()
        let command = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "music_search",
                "tool_name": "music_search",
                "phrase": "busca en Apple Music <artista o canción>",
                "description": "Abre los resultados.",
                "safety": "unsafe",
                "requires_confirmation": true,
            ])
        )

        model.useCommand(command)

        XCTAssertEqual(model.textCommand, "busca en Apple Music <artista o canción>")
        XCTAssertFalse(model.requestInProgress)
        XCTAssertNil(model.pendingConfirmation)
    }

    func testCatalogRejectsDuplicateAndOversizedCommandLists() throws {
        let payload: [String: Any] = [
            "id": "music_open",
            "tool_name": "music_open",
            "phrase": "abre Apple Music",
            "description": "Abre Apple Music.",
            "safety": "unsafe",
            "requires_confirmation": true,
        ]

        XCTAssertThrowsError(
            try PipaMobileViewModel.parseCatalogCommands([payload, payload])
        )
        XCTAssertThrowsError(
            try PipaMobileViewModel.parseCatalogCommands(Array(repeating: payload, count: 65))
        )
    }

    func testCatalogCommandEditorRendersBoundedArgumentsWithoutSending() throws {
        let command = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "whatsapp_compose",
                "tool_name": "whatsapp_compose",
                "phrase": "prepara WhatsApp para <teléfono> y dile <mensaje>",
                "description": "Prepara el chat.",
                "safety": "unsafe",
                "requires_confirmation": true,
            ])
        )

        XCTAssertEqual(command.placeholders, ["teléfono", "mensaje"])
        XCTAssertEqual(
            command.rendered(with: ["teléfono": "+34 600 123 456", "mensaje": "Hola"]),
            "prepara WhatsApp para +34 600 123 456 y dile Hola"
        )
        XCTAssertNil(command.rendered(with: ["teléfono": "+34 600 123 456", "mensaje": "Hola\nMundo"]))
    }

    func testStructuredCatalogCommandAcceptsMessageLineFeedsAndTypedArguments() throws {
        let command = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "whatsapp_compose",
                "tool_name": "whatsapp_compose",
                "phrase": "prepara WhatsApp para <teléfono> y dile <mensaje>",
                "description": "Prepara el chat.",
                "safety": "unsafe",
                "requires_confirmation": true,
                "parameters": [
                    ["name": "phone", "label": "Teléfono", "kind": "phone", "max_length": 32],
                    ["name": "message", "label": "Mensaje", "kind": "message", "max_length": 3800],
                ],
            ])
        )

        XCTAssertEqual(command.parameters.map(\.id), ["phone", "message"])
        XCTAssertEqual(
            command.toolArguments(with: ["teléfono": "+34 600 123 456", "mensaje": "Hola\nMundo"])?["phone"] as? String,
            "+34 600 123 456"
        )
        XCTAssertEqual(
            command.toolArguments(with: ["teléfono": "+34 600 123 456", "mensaje": "Hola\nMundo"])?["message"] as? String,
            "Hola\nMundo"
        )
        XCTAssertEqual(
            command.rendered(with: ["teléfono": "+34 600 123 456", "mensaje": "Hola\nMundo"]),
            "prepara WhatsApp para +34 600 123 456 y dile Hola\nMundo"
        )
    }

    func testStructuredDiscordServerChannelUsesTypedGuildAndChannelIDs() throws {
        let command = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "discord_server_channel",
                "tool_name": "discord_open",
                "phrase": "abre Discord servidor <servidor> canal <canal>",
                "description": "Abre un canal de servidor.",
                "safety": "unsafe",
                "requires_confirmation": true,
                "parameters": [
                    ["name": "guild_id", "label": "ID del servidor", "kind": "guild_id", "max_length": 20],
                    ["name": "channel_id", "label": "ID del canal", "kind": "channel_id", "max_length": 20],
                ],
            ])
        )

        let arguments = command.toolArguments(with: [
            "servidor": "98765432109876543",
            "canal": "12345678901234567",
        ])
        XCTAssertEqual(arguments?["guild_id"] as? String, "98765432109876543")
        XCTAssertEqual(arguments?["channel_id"] as? String, "12345678901234567")
        XCTAssertNil(
            command.toolArguments(with: [
                "servidor": "98765432109876543",
                "canal": "not-a-discord-id",
            ])
        )
        XCTAssertNil(
            command.toolArguments(with: [
                "servidor": "098765432109876543",
                "canal": "12345678901234567",
            ])
        )
    }

    func testStructuredWhatsAppRejectsInvalidPhoneBeforeTransport() throws {
        let command = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "whatsapp_compose",
                "tool_name": "whatsapp_compose",
                "phrase": "prepara WhatsApp para <teléfono> y dile <mensaje>",
                "description": "Prepara el chat.",
                "safety": "unsafe",
                "requires_confirmation": true,
                "parameters": [
                    ["name": "phone", "label": "Teléfono", "kind": "phone", "max_length": 32],
                    ["name": "message", "label": "Mensaje", "kind": "message", "max_length": 3800],
                ],
            ])
        )

        XCTAssertNil(command.toolArguments(with: [
            "teléfono": "123",
            "mensaje": "Hola",
        ]))
        XCTAssertNil(command.toolArguments(with: [
            "teléfono": "01234567",
            "mensaje": "Hola",
        ]))
    }

    func testNoArgumentCatalogCommandCanUseStructuredExecution() throws {
        let command = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "discord_open_app",
                "tool_name": "discord_open_app",
                "phrase": "abre Discord",
                "description": "Abre Discord.",
                "safety": "unsafe",
                "requires_confirmation": true,
                "parameters": [],
            ])
        )

        XCTAssertTrue(command.supportsStructuredArguments)
        XCTAssertEqual(command.toolArguments(with: [:])?.count, 0)
        XCTAssertNil(command.toolArguments(with: ["unexpected": "value"]))

        let legacyCommand = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "discord_open_app",
                "tool_name": "discord_open_app",
                "phrase": "abre Discord",
                "description": "Abre Discord.",
                "safety": "unsafe",
                "requires_confirmation": true,
            ])
        )
        XCTAssertFalse(legacyCommand.supportsStructuredArguments)
        XCTAssertNil(legacyCommand.toolArguments(with: [:]))
    }

    func testDirectCatalogCommandUsesValidatedDefaultArguments() throws {
        let command = try XCTUnwrap(
            PipaMobileCommand(payload: [
                "id": "media_play_pause",
                "tool_name": "media_action",
                "phrase": "reproduce la canción seleccionada",
                "description": "Controla el reproductor activo.",
                "safety": "safe",
                "requires_confirmation": false,
                "parameters": [],
                "default_arguments": ["action": "play_pause"],
            ])
        )

        XCTAssertTrue(command.supportsStructuredArguments)
        XCTAssertEqual(command.defaultArguments, ["action": "play_pause"])
        XCTAssertEqual(command.toolArguments(with: [:])?["action"] as? String, "play_pause")
        XCTAssertNil(command.toolArguments(with: ["unexpected": "value"]))
    }

    func testDirectCatalogCommandRejectsMalformedDefaultArguments() {
        let command = PipaMobileCommand(payload: [
            "id": "media_play_pause",
            "tool_name": "media_action",
            "phrase": "reproduce la canción seleccionada",
            "description": "Controla el reproductor activo.",
            "safety": "safe",
            "requires_confirmation": false,
            "parameters": [],
            "default_arguments": ["action": "play_pause\u{202E}"],
        ])

        XCTAssertNil(command)
    }

    func testStructuredCatalogCommandRejectsMalformedParameterMetadata() {
        let command = PipaMobileCommand(payload: [
            "id": "bad",
            "tool_name": "whatsapp_compose",
            "phrase": "prepara WhatsApp para <teléfono>",
            "description": "Prepara el chat.",
            "safety": "unsafe",
            "requires_confirmation": true,
            "parameters": [
                ["name": "phone", "label": "Teléfono", "kind": "unknown", "max_length": 32],
            ],
        ])

        XCTAssertNil(command)

        let extraFieldCommand = PipaMobileCommand(payload: [
            "id": "bad",
            "tool_name": "whatsapp_compose",
            "phrase": "prepara WhatsApp para <teléfono>",
            "description": "Prepara el chat.",
            "safety": "unsafe",
            "requires_confirmation": true,
            "parameters": [
                [
                    "name": "phone",
                    "label": "Teléfono",
                    "kind": "phone",
                    "max_length": 32,
                    "private": "must not cross the catalog boundary",
                ],
            ],
        ])

        XCTAssertNil(extraFieldCommand)
    }

    func testVoiceDraftOnlyUpdatesTheEditorWithoutSending() {
        let model = PipaMobileViewModel()

        model.updateVoiceDraft("busca una partida en el LoL")

        XCTAssertEqual(model.textCommand, "busca una partida en el LoL")
        XCTAssertFalse(model.requestInProgress)
        XCTAssertNil(model.pendingConfirmation)
    }

    func testVoiceDraftRejectsControlCharactersAndOversizedInput() {
        let model = PipaMobileViewModel()

        model.updateVoiceDraft("comando\nno permitido")
        XCTAssertEqual(model.textCommand, "")

        model.updateVoiceDraft(String(repeating: "a", count: 4001))
        XCTAssertEqual(model.textCommand, "")

        model.updateVoiceDraft("comando\u{202E}oculto")
        XCTAssertEqual(model.textCommand, "")
    }

    func testCatalogRejectsInconsistentSafetyMetadata() {
        let command = PipaMobileCommand(payload: [
            "id": "music_search",
            "tool_name": "music_search",
            "phrase": "busca en Apple Music <artista o canción>",
            "description": "Abre los resultados.",
            "safety": "unsafe",
            "requires_confirmation": false,
        ])

        XCTAssertNil(command)
    }

    func testCatalogRejectsBidirectionalFormattingControls() {
        let command = PipaMobileCommand(payload: [
            "id": "music_search\u{202E}",
            "tool_name": "music_search",
            "phrase": "busca en Apple Music",
            "description": "Abre los resultados.",
            "safety": "unsafe",
            "requires_confirmation": true,
        ])

        XCTAssertNil(command)
    }

    func testConnectionSettingsLoadAndForgetAreSeparateFromIdentity() {
        let store = MemorySettingsStore()
        store.settings = PipaMobileSettings(
            host: "192.168.1.20",
            port: "18765",
            serverID: "pipa-agent-v2",
            serverPublicKey: "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA",
            identityID: "iphone-main"
        )
        let model = PipaMobileViewModel(settingsStore: store)

        XCTAssertEqual(model.host, "192.168.1.20")
        XCTAssertEqual(model.serverID, "pipa-agent-v2")

        model.forgetConnectionSettings()

        XCTAssertTrue(store.deleteCalled)
        XCTAssertTrue(model.serverPublicKey.isEmpty)
        XCTAssertEqual(model.port, "18765")
    }

    func testConnectionRequiresEphemeralFingerprintAcknowledgement() {
        let model = PipaMobileViewModel()
        model.serverPublicKey = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA"

        XCTAssertFalse(model.serverFingerprintVerified)
        model.markServerFingerprintVerified()
        XCTAssertTrue(model.serverFingerprintVerified)

        model.serverID = "another-agent"
        XCTAssertFalse(model.serverFingerprintVerified)

        model.serverID = "pipa-agent-v2"
        model.markServerFingerprintVerified()
        model.serverPublicKey = "AgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4fICE"
        XCTAssertFalse(model.serverFingerprintVerified)

        model.invalidateServerFingerprintVerification()
        XCTAssertFalse(model.serverFingerprintVerified)
    }

    func testSavedSettingsNeverCountAsFingerprintAcknowledgement() {
        let store = MemorySettingsStore()
        store.settings = PipaMobileSettings(
            host: "192.168.1.20",
            port: "18765",
            serverID: "pipa-agent-v2",
            serverPublicKey: "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA",
            identityID: "iphone-main"
        )

        let model = PipaMobileViewModel(settingsStore: store)

        XCTAssertFalse(model.serverFingerprintVerified)
    }
}
