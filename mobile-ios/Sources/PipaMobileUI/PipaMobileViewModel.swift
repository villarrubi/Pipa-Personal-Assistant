import Combine
import Foundation
import PipaMobileCore

public enum PipaMobileConnectionState: String {
    case disconnected
    case connecting
    case connected
    case awaitingConfirmation

    public var label: String {
        switch self {
        case .disconnected:
            return "Desconectado"
        case .connecting:
            return "Conectando"
        case .connected:
            return "Conectado"
        case .awaitingConfirmation:
            return "Esperando confirmación"
        }
    }
}

public struct PipaMobileCommand: Identifiable {
    public let id: String
    public let toolName: String
    public let phrase: String
    public let description: String
    public let safety: String
    public let requiresConfirmation: Bool

    init?(payload: [String: Any]) {
        guard let id = payload["id"] as? String,
              let toolName = payload["tool_name"] as? String,
              let phrase = payload["phrase"] as? String,
              let description = payload["description"] as? String,
              let safety = payload["safety"] as? String,
              let requiresConfirmation = payload["requires_confirmation"] as? Bool,
              !id.isEmpty,
              !toolName.isEmpty,
              !phrase.isEmpty,
              !description.isEmpty,
              PipaMobileTextPolicy.isSafeDisplayText(id, maxBytes: 128),
              PipaMobileTextPolicy.isSafeDisplayText(toolName, maxBytes: 80),
              PipaMobileTextPolicy.isSafeDisplayText(phrase, maxBytes: 256),
              PipaMobileTextPolicy.isSafeDisplayText(description, maxBytes: 256),
              id.utf8.count <= 128,
              toolName.utf8.count <= 80,
              phrase.utf8.count <= 256,
              description.utf8.count <= 256,
              requiresConfirmation == (safety == "unsafe"),
              safety == "safe" || safety == "unsafe" else {
            return nil
        }
        self.id = id
        self.toolName = toolName
        self.phrase = phrase
        self.description = description
        self.safety = safety
        self.requiresConfirmation = requiresConfirmation
    }
}

public struct PipaMobileIntegration: Identifiable {
    public let id: String
    public let title: String
    public let available: Bool
    public let detail: String

    init?(id: String, payload: [String: Any]) {
        let titles = [
            "web_search": "Internet",
            "apple_music": "Apple Music",
            "whatsapp": "WhatsApp",
            "discord": "Discord",
            "league": "League of Legends",
            "codex": "Codex",
        ]
        guard let title = titles[id],
              let available = payload["available"] as? Bool,
              id.utf8.count <= 64 else {
            return nil
        }

        self.id = id
        self.title = title
        self.available = available
        if !available {
            detail = "No configurado o no disponible en el PC."
        } else if id == "apple_music", payload["requires_manual_selection"] as? Bool == true {
            if payload["media_control"] as? Bool == true {
                detail = "Busca y selecciona la pista; controla reproducción/pausa manualmente."
            } else {
                detail = "Busca; selecciona y reproduce la pista manualmente."
            }
        } else if id == "whatsapp", payload["requires_manual_send"] as? Bool == true {
            if payload["contact_aliases_configured"] as? Bool == false {
                detail = "Puedes usar un teléfono; no hay alias locales. Pulsa Enviar manualmente."
            } else {
                detail = "Prepara el chat; pulsa Enviar manualmente."
            }
        } else if id == "discord", payload["requires_manual_call"] as? Bool == true {
            if payload["contact_aliases_configured"] as? Bool == false {
                detail = "Puedes usar un ID; no hay alias locales. Inicia la llamada manualmente."
            } else {
                detail = "Abre el canal; inicia la llamada manualmente."
            }
        } else if id == "league", payload["client_ready"] as? Bool == false {
            detail = "El cliente está configurado, pero no está listo ahora."
        } else {
            detail = "Disponible con confirmación cuando corresponda."
        }
    }
}

public struct PipaMobileConfirmation {
    public let confirmationID: String
    public let toolName: String
    public let summary: String
}

@available(iOS 16.0, macOS 13.0, *)
@MainActor
public final class PipaMobileViewModel: ObservableObject {
    private static let deviceConfirmationSummaries: [String: String] = [
        "open_app": "Abrir una aplicación configurada.",
        "open_codex": "Abrir Codex.",
        "web_search": "Buscar en Internet.",
        "music_search": "Buscar en Apple Music.",
        "music_open": "Abrir Apple Music.",
        "league_open": "Abrir League of Legends.",
        "discord_open_app": "Abrir Discord.",
        "discord_open": "Abrir un canal de Discord.",
        "discord_contact": "Abrir un contacto de Discord.",
        "discord_call": "Preparar una llamada de Discord; el inicio será manual.",
        "whatsapp_compose": "Preparar un mensaje de WhatsApp; el envío será manual.",
        "whatsapp_contact": "Preparar un mensaje de WhatsApp; el envío será manual.",
        "whatsapp_contact_open": "Abrir un chat de WhatsApp.",
        "whatsapp_open": "Abrir WhatsApp Web.",
        "league_search": "Buscar una partida en League.",
        "league_cancel": "Cancelar la búsqueda de League.",
        "system_lock": "Bloquear el ordenador.",
        "open_url": "Abrir una URL validada.",
    ]

    @Published public var host = ""
    @Published public var port = "18765"
    @Published public var serverID = "pipa-agent-v2"
    @Published public var serverPublicKey = ""
    @Published public var identityID = "iphone-main"
    @Published public var textCommand = ""
    @Published private(set) var verifiedServerFingerprint: String? = nil
    private var verifiedServerID: String?

    @Published public private(set) var connectionState: PipaMobileConnectionState = .disconnected
    @Published public private(set) var commands: [PipaMobileCommand] = []
    @Published public private(set) var integrationCapabilities: [PipaMobileIntegration] = []
    @Published public private(set) var pendingConfirmation: PipaMobileConfirmation?
    @Published public private(set) var identityPublicKey: String?
    @Published public private(set) var identityFingerprint: String?
    @Published public private(set) var statusMessage: String?
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var requestInProgress = false

    private let identityStore: PipaKeychainIdentityStore
    private let settingsStore: any PipaMobileSettingsStoring
    private var client: PipaMobileTCPClient?
    private var operationTask: Task<Void, Never>?
    private var requestTask: Task<Void, Never>?
    private var connectInProgress = false
    private var sessionGeneration = 0

    public init(
        identityStore: PipaKeychainIdentityStore = PipaKeychainIdentityStore(),
        settingsStore: any PipaMobileSettingsStoring = PipaMobileSettingsStore()
    ) {
        self.identityStore = identityStore
        self.settingsStore = settingsStore
        do {
            if let settings = try settingsStore.load() {
                host = settings.host
                port = settings.port
                serverID = settings.serverID
                serverPublicKey = settings.serverPublicKey
                identityID = settings.identityID
            }
        } catch {
            // A locked or corrupt optional settings item must not prevent the
            // UI from opening; the user can enter a fresh configuration.
        }
    }

    public var isConnected: Bool {
        connectionState == .connected || connectionState == .awaitingConfirmation
    }

    /// Fingerprint of the pinned Windows agent key, for out-of-band comparison.
    public var serverFingerprint: String? {
        guard let data = try? PipaMobileIdentity.decodePublicKeyBase64URL(serverPublicKey) else {
            return nil
        }
        return PipaMobileIdentity.publicKeyDigest(forPublicKeyData: data)
    }

    public var serverFingerprintVerified: Bool {
        guard let currentFingerprint = serverFingerprint else { return false }
        return verifiedServerFingerprint == currentFingerprint && verifiedServerID == serverID
    }

    /// Mark the currently displayed agent fingerprint as compared out of band.
    /// This acknowledgement is intentionally ephemeral and is never persisted.
    public func markServerFingerprintVerified() {
        guard let currentFingerprint = serverFingerprint else {
            fail("Introduce una clave pública válida antes de verificar el fingerprint.")
            return
        }
        verifiedServerFingerprint = currentFingerprint
        verifiedServerID = serverID
        errorMessage = nil
        statusMessage = "Fingerprint verificado para esta sesión de configuración."
    }

    /// Any edit to the pinned identity invalidates the previous acknowledgement.
    public func invalidateServerFingerprintVerification() {
        verifiedServerFingerprint = nil
        verifiedServerID = nil
    }

    public func prepareIdentity() {
        do {
            let identity = try identityStore.loadOrCreate(identityID: identityID)
            identityPublicKey = identity.publicKeyBase64URL
            identityFingerprint = identity.fingerprint
            errorMessage = nil
            statusMessage = "Identidad preparada. Compara el fingerprint antes de emparejar."
            saveSettings()
        } catch {
            identityPublicKey = nil
            identityFingerprint = nil
            fail("No se pudo crear o cargar la identidad del iPhone.")
        }
    }

    /// Put a catalog phrase in the editor without sending or executing it.
    /// Placeholders such as `<consulta>` remain visible so the user can edit
    /// them before an explicit send.
    public func useCommand(_ command: PipaMobileCommand) {
        useCommandText(command.phrase)
    }

    /// Put a completed catalog phrase in the editor without sending it.
    public func useCommandText(_ text: String) {
        textCommand = text
        errorMessage = nil
        statusMessage = "Comando preparado; revisa los marcadores antes de enviarlo."
    }

    /// Update the editor from local iPhone dictation without sending anything.
    public func updateVoiceDraft(_ text: String) {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty,
              value.utf8.count <= 4000,
              !PipaMobileTextPolicy.containsDisplayControl(value) else {
            return
        }
        textCommand = value
        errorMessage = nil
        statusMessage = "Dictado preparado; revisa el comando antes de enviarlo."
    }

    /// Remove only the saved endpoint configuration; the signing identity is
    /// deliberately kept in its separate Keychain record.
    public func forgetConnectionSettings() {
        if isConnected {
            disconnect()
        }
        do {
            try settingsStore.delete()
            host = ""
            port = "18765"
            serverID = "pipa-agent-v2"
            serverPublicKey = ""
            identityID = "iphone-main"
            invalidateServerFingerprintVerification()
            statusMessage = "Configuración guardada eliminada."
            errorMessage = nil
        } catch {
            fail("No se pudo eliminar la configuración guardada.")
        }
    }

    public func connect() {
        guard client == nil, !connectInProgress else { return }
        guard serverFingerprintVerified else {
            fail("Compara el fingerprint del agente por un canal externo y márcalo como verificado.")
            return
        }
        guard let portValue = UInt16(port), portValue != 0,
              let serverKey = try? PipaMobileIdentity.decodePublicKeyBase64URL(serverPublicKey),
              !host.isEmpty,
              !serverID.isEmpty,
              !identityID.isEmpty else {
            fail("Revisa la IP, el puerto, el server_id y la clave pública del agente.")
            return
        }

        connectionState = .connecting
        clearMessages()
        saveSettings()
        do {
            let identity = try identityStore.loadOrCreate(identityID: identityID)
            identityPublicKey = identity.publicKeyBase64URL
            identityFingerprint = identity.fingerprint
            let newClient = try PipaMobileTCPClient(
                identity: identity,
                serverPublicKeyData: serverKey,
                serverID: serverID,
                firmwareVersion: "pipa-ios-ui"
            )
            client = newClient
            connectInProgress = true
            let connectHost = host
            let connectTask = Task { [weak self, newClient, connectHost, portValue] in
                do {
                    try await newClient.connect(host: connectHost, port: portValue)
                    guard !Task.isCancelled else {
                        await newClient.disconnect()
                        self?.connectInProgress = false
                        return
                    }
                    let catalog = try await newClient.requestCatalogDetails()
                    guard !Task.isCancelled else {
                        await newClient.disconnect()
                        self?.connectInProgress = false
                        return
                    }
                    let parsedCatalog = catalog.commands.compactMap(PipaMobileCommand.init(payload:))
                    guard parsedCatalog.count == catalog.commands.count else {
                        throw PipaMobileError.invalidMessage
                    }
                    let parsedCapabilities = catalog.capabilities
                        .compactMap { PipaMobileIntegration(id: $0.key, payload: $0.value) }
                        .sorted { $0.id < $1.id }
                    self?.commands = parsedCatalog
                    self?.integrationCapabilities = parsedCapabilities
                    self?.connectInProgress = false
                    self?.connectionState = .connected
                    self?.statusMessage = "Conectado."
                } catch {
                    await newClient.disconnect()
                    if Task.isCancelled {
                        self?.connectInProgress = false
                        return
                    }
                    self?.client = nil
                    self?.connectInProgress = false
                    self?.connectionState = .disconnected
                    self?.fail("No se pudo establecer la sesión segura.")
                }
            }
            operationTask = connectTask
        } catch {
            fail("No se pudo preparar la identidad segura del iPhone.")
        }
    }

    public func disconnect() {
        sessionGeneration += 1
        operationTask?.cancel()
        operationTask = nil
        requestTask?.cancel()
        requestTask = nil
        connectInProgress = false
        requestInProgress = false
        let activeClient = client
        client = nil
        commands = []
        integrationCapabilities = []
        pendingConfirmation = nil
        connectionState = .disconnected
        statusMessage = "Desconectado."
        Task {
            await activeClient?.disconnect()
        }
    }

    public func sendTextCommand() {
        let text = textCommand.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty,
              !requestInProgress,
              pendingConfirmation == nil,
              let activeClient = client else { return }
        textCommand = ""
        clearMessages()
        requestInProgress = true
        let generation = sessionGeneration
        let task = Task { [weak self, activeClient, generation] in
            do {
                let responses = try await activeClient.sendText(text)
                guard !Task.isCancelled, self?.sessionGeneration == generation else { return }
                guard self?.apply(responses: responses) == true else {
                    self?.closeAfterOperationFailure(
                        activeClient,
                        message: "La respuesta del agente no es válida."
                    )
                    return
                }
            } catch {
                guard !Task.isCancelled, self?.sessionGeneration == generation else { return }
                self?.closeAfterOperationFailure(
                    activeClient,
                    message: "No se pudo enviar el comando."
                )
            }
            self?.requestInProgress = false
            self?.requestTask = nil
        }
        requestTask = task
    }

    public func resolveConfirmation(accepted: Bool) {
        guard !requestInProgress,
              let pending = pendingConfirmation,
              let activeClient = client else { return }
        pendingConfirmation = nil
        requestInProgress = true
        let generation = sessionGeneration
        let task = Task { [weak self, activeClient, generation] in
            do {
                let responses = try await activeClient.confirm(
                    confirmationID: pending.confirmationID,
                    accepted: accepted
                )
                guard !Task.isCancelled, self?.sessionGeneration == generation else { return }
                guard self?.apply(responses: responses) == true else {
                    self?.closeAfterOperationFailure(
                        activeClient,
                        message: "La respuesta del agente no es válida."
                    )
                    return
                }
            } catch {
                guard !Task.isCancelled, self?.sessionGeneration == generation else { return }
                self?.closeAfterOperationFailure(
                    activeClient,
                    message: "No se pudo resolver la confirmación."
                )
            }
            self?.requestInProgress = false
            self?.requestTask = nil
        }
        requestTask = task
    }

    static func isSafeConfirmationSummary(toolName: String, summary: String) -> Bool {
        let expected = deviceConfirmationSummaries[toolName] ?? "Confirmar acción externa."
        return summary == expected
    }

    private func apply(responses: [[String: Any]]) -> Bool {
        for response in responses {
            guard let type = response["type"] as? String,
                  PipaMobileTextPolicy.isSafeDisplayText(type, maxBytes: 64) else {
                return false
            }
            switch type {
            case "confirm_request":
                guard let confirmationID = response["confirmation_id"] as? String,
                      let toolName = response["tool_name"] as? String,
                      let summary = response["summary"] as? String,
                      !confirmationID.isEmpty,
                      !toolName.isEmpty,
                      !summary.isEmpty,
                      PipaMobileTextPolicy.isSafeDisplayText(confirmationID, maxBytes: 128),
                      PipaMobileTextPolicy.isSafeDisplayText(toolName, maxBytes: 80),
                      PipaMobileTextPolicy.isSafeDisplayText(summary, maxBytes: 512),
                      confirmationID.utf8.count <= 128,
                      toolName.utf8.count <= 80,
                      summary.utf8.count <= 512,
                      Self.isSafeConfirmationSummary(toolName: toolName, summary: summary) else {
                    return false
                }
                pendingConfirmation = PipaMobileConfirmation(
                    confirmationID: confirmationID,
                    toolName: toolName,
                    summary: summary
                )
                connectionState = .awaitingConfirmation
            case "tool_result":
                guard let toolName = response["tool_name"] as? String,
                      let status = response["status"] as? String,
                      response["success"] is Bool,
                      !toolName.isEmpty,
                      !status.isEmpty,
                      PipaMobileTextPolicy.isSafeDisplayText(toolName, maxBytes: 80),
                      PipaMobileTextPolicy.isSafeDisplayText(status, maxBytes: 32),
                      toolName.utf8.count <= 80,
                      status.utf8.count <= 32 else {
                    return false
                }
                if let callIDValue = response["call_id"], !(callIDValue is NSNull) {
                    guard let callID = callIDValue as? String,
                          !callID.isEmpty,
                          PipaMobileTextPolicy.isSafeDisplayText(callID, maxBytes: 128),
                          callID.utf8.count <= 128 else {
                        return false
                    }
                }
            case "ui_state":
                guard let state = response["state"] as? String,
                      ["idle", "listening", "thinking", "confirm", "speaking", "focus", "dashboard"].contains(state)
                else {
                    return false
                }
                if let caption = response["caption"], !(caption is NSNull) {
                    guard let captionText = caption as? String,
                          PipaMobileTextPolicy.isSafeDisplayText(captionText, maxBytes: 512),
                          captionText.utf8.count <= 512 else {
                        return false
                    }
                }
                if let focusRemaining = response["focus_remaining"], !(focusRemaining is NSNull) {
                    guard let focusValue = focusRemaining as? Int, focusValue >= 0 else {
                        return false
                    }
                }
                statusMessage = response["caption"] as? String
                if pendingConfirmation == nil {
                    connectionState = .connected
                }
            case "error":
                guard let code = response["code"] as? String,
                      !code.isEmpty,
                      PipaMobileTextPolicy.isSafeDisplayText(code, maxBytes: 64),
                      code.utf8.count <= 64 else {
                    return false
                }
                errorMessage = "El agente rechazó la operación."
                statusMessage = nil
                if client != nil {
                    connectionState = .connected
                }
            default:
                return false
            }
        }
        return true
    }

    private func closeAfterOperationFailure(
        _ activeClient: PipaMobileTCPClient,
        message: String
    ) {
        guard client != nil else { return }
        client = nil
        pendingConfirmation = nil
        requestInProgress = false
        connectionState = .disconnected
        errorMessage = message
        statusMessage = nil
        Task {
            await activeClient.disconnect()
        }
    }

    private func clearMessages() {
        statusMessage = nil
        errorMessage = nil
    }

    private func saveSettings() {
        let settings = PipaMobileSettings(
            host: host,
            port: port,
            serverID: serverID,
            serverPublicKey: serverPublicKey,
            identityID: identityID
        )
        do {
            try settingsStore.save(settings)
        } catch {
            statusMessage = "No se pudo guardar la configuración local."
        }
    }

    private func fail(_ message: String) {
        errorMessage = message
        statusMessage = nil
        if pendingConfirmation == nil {
            connectionState = .disconnected
        }
    }
}
