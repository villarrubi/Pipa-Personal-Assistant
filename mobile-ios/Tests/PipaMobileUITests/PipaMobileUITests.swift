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
            payload: ["available": true, "requires_manual_selection": true, "media_control": true]
        )
        let league = PipaMobileIntegration(
            id: "league",
            payload: ["available": true, "client_ready": false]
        )

        XCTAssertEqual(music?.title, "Apple Music")
        XCTAssertEqual(music?.detail, "Busca y selecciona la pista; controla reproducción/pausa manualmente.")
        XCTAssertEqual(league?.detail, "El cliente está configurado, pero no está listo ahora.")
        XCTAssertNil(PipaMobileIntegration(id: "unknown", payload: ["available": true]))
    }

    func testConfirmationSummaryRejectsArgumentsAndAllowsFixedLabels() {
        XCTAssertTrue(
            PipaMobileViewModel.isSafeConfirmationSummary(
                toolName: "whatsapp_compose",
                summary: "Preparar un mensaje de WhatsApp; el envío será manual."
            )
        )
        XCTAssertFalse(
            PipaMobileViewModel.isSafeConfirmationSummary(
                toolName: "whatsapp_compose",
                summary: "Preparar WhatsApp para +34 600 123 456: mensaje secreto"
            )
        )
        XCTAssertTrue(
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
