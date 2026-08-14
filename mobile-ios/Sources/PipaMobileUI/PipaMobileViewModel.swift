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

public struct PipaMobileCommandParameter: Identifiable {
    public let id: String
    public let label: String
    public let kind: String
    public let maxLength: Int
    public let options: [String]

    init?(payload: [String: Any]) {
        guard payload.keys.allSatisfy({ ["name", "label", "kind", "max_length", "options"].contains($0) }),
              let name = payload["name"] as? String,
              let label = payload["label"] as? String,
              let kind = payload["kind"] as? String,
              let maxLength = payload["max_length"] as? Int,
              Self.isValidName(name),
              !label.isEmpty,
              PipaMobileTextPolicy.isSafeDisplayText(label, maxBytes: 128),
              [
                  "text", "message", "phone", "integer", "queue", "action", "app", "contact",
                  "channel_id", "guild_id", "url",
              ].contains(kind),
              (1...4096).contains(maxLength),
              label.utf8.count <= 128 else {
            return nil
        }

        let options: [String]
        if let rawOptions = payload["options"] {
            guard let parsedOptions = rawOptions as? [String],
                  parsedOptions.count <= 16,
                  Set(parsedOptions).count == parsedOptions.count,
                  parsedOptions.allSatisfy({
                      !$0.isEmpty &&
                          $0.utf8.count <= 128 &&
                          PipaMobileTextPolicy.isSafeDisplayText($0, maxBytes: 128)
                  }) else {
                return nil
            }
            options = parsedOptions
        } else {
            options = []
        }

        self.id = name
        self.label = label
        self.kind = kind
        self.maxLength = maxLength
        self.options = options
    }

    private static func isValidName(_ value: String) -> Bool {
        guard let first = value.utf8.first,
              value.utf8.count <= 64,
              (first >= 0x41 && first <= 0x5A) || (first >= 0x61 && first <= 0x7A) else {
            return false
        }
        return value.utf8.dropFirst().allSatisfy { byte in
            (byte >= 0x41 && byte <= 0x5A) ||
                (byte >= 0x61 && byte <= 0x7A) ||
                (byte >= 0x30 && byte <= 0x39) ||
                byte == 0x2D || byte == 0x5F
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
    public let parameters: [PipaMobileCommandParameter]
    /// An empty explicit list is meaningful for direct no-argument calls.
    /// Missing metadata keeps the legacy text-editor path for old agents.
    public let supportsStructuredArguments: Bool
    /// Fixed typed arguments for direct catalog commands with no placeholders.
    /// They are validated locally before crossing the encrypted session.
    public let defaultArguments: [String: String]

    init?(payload: [String: Any]) {
        guard payload.keys.allSatisfy({
                  [
                      "id", "tool_name", "phrase", "description", "safety", "requires_confirmation",
                      "parameters", "default_arguments",
                  ].contains($0)
              }),
              let id = payload["id"] as? String,
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

        let parameters: [PipaMobileCommandParameter]
        var supportsStructuredArguments: Bool
        if payload.keys.contains("parameters") {
            guard let rawList = payload["parameters"] as? [[String: Any]],
                  rawList.count <= 8 else {
                return nil
            }
            let parsed = rawList.compactMap(PipaMobileCommandParameter.init(payload:))
            guard parsed.count == rawList.count,
                  Set(parsed.map(\.id)).count == parsed.count else {
                return nil
            }
            parameters = parsed
            supportsStructuredArguments = true
        } else {
            parameters = []
            supportsStructuredArguments = false
        }

        let defaultArguments: [String: String]
        if let rawDefaults = payload["default_arguments"] {
            guard let defaults = rawDefaults as? [String: Any],
                  !defaults.isEmpty,
                  defaults.count <= 8,
                  defaults.allSatisfy({ key, value in
                      Self.isValidDefaultArgumentName(key) &&
                          (value as? String).map {
                              PipaMobileTextPolicy.isSafeDisplayText($0, maxBytes: 128) && $0.utf8.count <= 128
                          } == true
                  }),
                  parameters.isEmpty else {
                return nil
            }
            defaultArguments = defaults.compactMapValues { $0 as? String }
            supportsStructuredArguments = true
        } else {
            defaultArguments = [:]
        }

        self.id = id
        self.toolName = toolName
        self.phrase = phrase
        self.description = description
        self.safety = safety
        self.requiresConfirmation = requiresConfirmation
        self.parameters = parameters
        self.supportsStructuredArguments = supportsStructuredArguments
        self.defaultArguments = defaultArguments
    }

    private static func isValidDefaultArgumentName(_ value: String) -> Bool {
        guard let first = value.utf8.first,
              value.utf8.count <= 64,
              (first >= 0x41 && first <= 0x5A) || (first >= 0x61 && first <= 0x7A) else {
            return false
        }
        return value.utf8.dropFirst().allSatisfy { byte in
            (byte >= 0x41 && byte <= 0x5A) ||
                (byte >= 0x61 && byte <= 0x7A) ||
                (byte >= 0x30 && byte <= 0x39) ||
                byte == 0x2D || byte == 0x5F
        }
    }
}

public struct PipaMobileIntegration: Identifiable {
    public let id: String
    public let title: String
    public let available: Bool
    public let appConfigured: Bool
    public let launcherResolved: Bool
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
        self.appConfigured = payload["app_configured"] as? Bool ?? false
        self.launcherResolved = payload["launcher_resolved"] as? Bool ?? self.appConfigured
        if !available {
            detail = "No configurado o no disponible en el PC."
        } else if appConfigured && !launcherResolved {
            detail = "Está configurado, pero no se encuentra el lanzador local; revisa la configuración del PC."
        } else if id == "apple_music", payload["requires_manual_selection"] as? Bool == true {
            if payload["media_control"] as? Bool == true {
                if appConfigured {
                    detail = "App disponible; busca y selecciona la pista y controla reproducción/pausa manualmente."
                } else {
                    detail = "Apple Music Web disponible; busca y selecciona la pista y controla reproducción/pausa manualmente."
                }
            } else {
                detail = "Busca; selecciona y reproduce la pista manualmente."
            }
        } else if id == "whatsapp", payload["requires_manual_send"] as? Bool == true {
            if payload["contact_aliases_configured"] as? Bool == false {
                let target = appConfigured ? "App disponible" : "WhatsApp Web disponible"
                detail = "\(target); puedes usar un teléfono. Pulsa Enviar manualmente."
            } else {
                let target = appConfigured ? "App disponible" : "WhatsApp Web disponible"
                detail = "\(target); prepara el chat y pulsa Enviar manualmente."
            }
        } else if id == "discord", payload["requires_manual_call"] as? Bool == true {
            if payload["contact_aliases_configured"] as? Bool == false {
                let target = appConfigured ? "App disponible" : "Discord Web disponible"
                detail = "\(target); puedes usar un ID. Inicia la llamada manualmente."
            } else {
                let target = appConfigured ? "App disponible" : "Discord Web disponible"
                detail = "\(target); abre el canal e inicia la llamada manualmente."
            }
        } else if id == "league", payload["client_ready"] as? Bool == false {
            detail = "El cliente está configurado, pero no está listo ahora; aceptar la partida será manual."
        } else if id == "league", payload["requires_manual_accept"] as? Bool == true {
            detail = "Puedes buscar partida; cuando aparezca, tendrás que aceptarla manualmente."
        } else {
            detail = "Disponible con confirmación cuando corresponda."
        }
    }
}

public struct PipaMobileConfirmation {
    public let confirmationID: String
    public let toolName: String
    public let summary: String
    /// Optional preview retained only in the iPhone process. It is derived
    /// from the text/typed fields the user just submitted and is never sent
    /// back in the confirmation protocol.
    public let localPreview: String?
    /// Structured commands know the tool the user selected locally. A
    /// mismatch must never be silently accepted.
    public let localPreviewToolName: String?

    public var localPreviewMatchesServerAction: Bool {
        guard let localPreviewToolName else { return true }
        return localPreviewToolName == toolName
    }
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
        "discord_call_channel": "Preparar una llamada de Discord; el inicio será manual.",
        "discord_contact": "Abrir un contacto de Discord.",
        "discord_call": "Preparar una llamada de Discord; el inicio será manual.",
        "whatsapp_compose": "Preparar un mensaje de WhatsApp; el envío será manual.",
        "whatsapp_contact": "Preparar un mensaje de WhatsApp; el envío será manual.",
        "whatsapp_contact_open": "Abrir un chat de WhatsApp.",
        "whatsapp_phone_open": "Abrir un chat de WhatsApp.",
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
    private var pendingLocalPreview: String?
    private var pendingLocalPreviewToolName: String?

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
        } else {
            // The settings action is also a privacy boundary when no session
            // exists: discard any locally prepared command before resetting
            // the endpoint fields.
            clearCommandDraft()
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
                    let parsedCatalog = try Self.parseCatalogCommands(catalog.commands)
                    let parsedCapabilities = try Self.parseIntegrationCapabilities(catalog.capabilities)
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
        // A draft may contain a private message or a command transcribed from
        // the microphone.  Leaving the session must not leave that content
        // visible in the editor after the app enters the background.
        clearCommandDraft()
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
              client != nil else { return }
        textCommand = ""
        pendingLocalPreview = Self.safeLocalPreview(text)
        pendingLocalPreviewToolName = nil
        startRequest(failureMessage: "No se pudo enviar el comando.") { activeClient in
            try await activeClient.sendText(text)
        }
    }

    /// Send a catalog command with validated typed arguments instead of
    /// relying on the Spanish text parser. The visible preview is shown by
    /// the editor before this method is called; unsafe tools still stop at
    /// the normal confirmation screen.
    public func sendStructuredCommand(
        _ command: PipaMobileCommand,
        values: [String: String]
    ) {
        guard let arguments = command.toolArguments(with: values) else {
            fail("Completa los campos con valores válidos.")
            return
        }
        guard !requestInProgress, pendingConfirmation == nil, client != nil else { return }
        textCommand = ""
        pendingLocalPreview = command.rendered(with: values)
        pendingLocalPreviewToolName = command.toolName
        startRequest(failureMessage: "No se pudo enviar la acción estructurada.") { activeClient in
            try await activeClient.callTool(name: command.toolName, arguments: arguments)
        }
    }

    public func resolveConfirmation(accepted: Bool) {
        guard !requestInProgress,
              let pending = pendingConfirmation,
              client != nil else { return }
        pendingConfirmation = nil
        clearLocalPreview()
        startRequest(failureMessage: "No se pudo resolver la confirmación.") { activeClient in
            try await activeClient.confirm(
                confirmationID: pending.confirmationID,
                accepted: accepted
            )
        }
    }

    static func isSafeConfirmationSummary(toolName: String, summary: String) -> Bool {
        guard let expected = deviceConfirmationSummaries[toolName] else {
            return false
        }
        return summary == expected
    }

    /// Keep the exact local command useful for review without allowing it to
    /// become an unbounded or visually deceptive UI string.
    static func safeLocalPreview(_ text: String) -> String? {
        guard PipaMobileTextPolicy.isSafeMessageText(text, maxBytes: 4000) else {
            return nil
        }
        return text
    }

    static func parseCatalogCommands(_ rawCommands: [[String: Any]]) throws -> [PipaMobileCommand] {
        guard rawCommands.count <= 64 else {
            throw PipaMobileError.invalidMessage
        }
        let parsed = rawCommands.compactMap(PipaMobileCommand.init(payload:))
        guard parsed.count == rawCommands.count,
              Set(parsed.map(\.id)).count == parsed.count else {
            throw PipaMobileError.invalidMessage
        }
        return parsed
    }

    /// Capability groups are display metadata, but they arrive inside the
    /// authenticated catalog and must still be parsed atomically. Silently
    /// dropping an invalid group could make the UI show a partial, stale
    /// capability matrix while the rest of the session remains active.
    static func parseIntegrationCapabilities(
        _ rawCapabilities: [String: [String: Any]]
    ) throws -> [PipaMobileIntegration] {
        guard rawCapabilities.count <= 6 else {
            throw PipaMobileError.invalidMessage
        }
        let parsed = rawCapabilities.compactMap { key, value in
            PipaMobileIntegration(id: key, payload: value)
        }
        guard parsed.count == rawCapabilities.count,
              Set(parsed.map(\.id)).count == parsed.count else {
            throw PipaMobileError.invalidMessage
        }
        return parsed.sorted { $0.id < $1.id }
    }

    private func startRequest(
        failureMessage: String,
        operation: @escaping (PipaMobileTCPClient) async throws -> [[String: Any]]
    ) {
        guard !requestInProgress, pendingConfirmation == nil, let activeClient = client else { return }
        clearMessages()
        requestInProgress = true
        let generation = sessionGeneration
        let task = Task { [weak self, activeClient, generation] in
            do {
                let responses = try await operation(activeClient)
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
                self?.closeAfterOperationFailure(activeClient, message: failureMessage)
            }
            self?.requestInProgress = false
            self?.requestTask = nil
        }
        requestTask = task
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
                    summary: summary,
                    localPreview: pendingLocalPreview,
                    localPreviewToolName: pendingLocalPreviewToolName
                )
                clearLocalPreview()
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
                clearLocalPreview()
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
                clearLocalPreview()
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
        clearCommandDraft()
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

    private func clearLocalPreview() {
        pendingLocalPreview = nil
        pendingLocalPreviewToolName = nil
    }

    private func clearCommandDraft() {
        textCommand = ""
        pendingConfirmation = nil
        clearLocalPreview()
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
