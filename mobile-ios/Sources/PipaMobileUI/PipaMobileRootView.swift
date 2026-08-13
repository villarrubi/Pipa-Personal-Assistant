import PipaMobileCore
import SwiftUI

@available(iOS 16.0, macOS 13.0, *)
@MainActor
public struct PipaMobileRootView: View {
    @StateObject private var model: PipaMobileViewModel
    @StateObject private var localAppleMusic = PipaMobileAppleMusicController()
#if os(iOS)
    @StateObject private var speechRecognizer = PipaMobileSpeechRecognizer()
#endif
    @State private var commandToEdit: PipaMobileCommand?
    @State private var localMusicQuery = ""
    @State private var localWhatsAppPhone = ""
    @State private var localWhatsAppMessage = ""
    @State private var localDiscordChannelID = ""
    @State private var localDiscordGuildID = ""
    @State private var localIntegrationStatus = ""
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.openURL) private var openURL

    public init(model: PipaMobileViewModel? = nil) {
        _model = StateObject(wrappedValue: model ?? PipaMobileViewModel())
    }

    public var body: some View {
        NavigationStack {
            Form {
                connectionSection
                statusSection
                integrationSection
                localAppleMusicSection
                localMessagingSection
                commandSection
                catalogSection
            }
            .navigationTitle("Pipα")
        }
        .onChange(of: scenePhase) { phase in
            if phase != .active {
                model.disconnect()
#if os(iOS)
                speechRecognizer.stop()
#endif
            } else {
                localAppleMusic.refreshPlaybackState()
            }
        }
#if os(iOS)
        .onChange(of: speechRecognizer.transcript) { transcript in
            model.updateVoiceDraft(transcript)
        }
#endif
        .sheet(item: $commandToEdit) { command in
            PipaMobileCommandEditor(command: command) { rendered in
                model.useCommandText(rendered)
            } onExecute: { command, values in
                model.sendStructuredCommand(command, values: values)
            }
        }
    }

    private var connectionSection: some View {
        Section("Sesión segura") {
            TextField("IP privada del PC", text: $model.host)
#if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
#endif
            TextField("Puerto", text: $model.port)
#if os(iOS)
                .keyboardType(.numberPad)
#endif
            TextField("server_id", text: $model.serverID)
#if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
#endif
            TextField("Clave pública Ed25519 (base64url)", text: $model.serverPublicKey)
#if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
#endif
            if let serverFingerprint = model.serverFingerprint {
                Text("Fingerprint del agente: \(serverFingerprint)")
                    .font(.caption2)
                    .textSelection(.enabled)
                Button(
                    model.serverFingerprintVerified
                        ? "Fingerprint verificado"
                        : "He comparado el fingerprint"
                ) {
                    model.markServerFingerprintVerified()
                }
                .disabled(model.serverFingerprintVerified)
                .accessibilityHint("Debes comparar esta huella con el agente por un canal externo antes de conectar.")
            }
            TextField("Identidad de este iPhone", text: $model.identityID)
#if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
#endif
            Button("Preparar identidad y mostrar fingerprint") {
                model.prepareIdentity()
            }
            if let identityPublicKey = model.identityPublicKey {
                Text("Clave pública: \(identityPublicKey)")
                    .font(.caption2)
                    .textSelection(.enabled)
            }
            if let identityFingerprint = model.identityFingerprint {
                Text("Fingerprint: \(identityFingerprint)")
                    .font(.caption2)
                    .textSelection(.enabled)
            }
            Button(model.isConnected ? "Desconectar" : "Conectar") {
                if model.isConnected {
                    model.disconnect()
                } else {
                    model.connect()
                }
            }
            .disabled(model.connectionState == .connecting)
            Button("Borrar configuración guardada", role: .destructive) {
                model.forgetConnectionSettings()
            }
        }
        .onChange(of: model.serverPublicKey) { _ in
            model.invalidateServerFingerprintVerification()
        }
        .onChange(of: model.serverID) { _ in
            model.invalidateServerFingerprintVerification()
        }
    }

    private var statusSection: some View {
        Section("Estado") {
            Text(model.connectionState.label)
            if let statusMessage = model.statusMessage {
                Text(statusMessage)
                    .foregroundStyle(.secondary)
            }
            if let errorMessage = model.errorMessage {
                Text(errorMessage)
                    .foregroundStyle(.red)
            }
        }
    }

    private var integrationSection: some View {
        Section("Integraciones") {
            if model.integrationCapabilities.isEmpty {
                Text("Conecta el iPhone para consultar qué integraciones están listas.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(model.integrationCapabilities) { integration in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: integration.available ? "checkmark.circle.fill" : "minus.circle")
                            .foregroundStyle(integration.available ? .green : .secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(integration.title)
                                Spacer()
                                Text(integration.available ? "Disponible" : "No disponible")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                            Text(integration.detail)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    private var localAppleMusicSection: some View {
        Section("Apple Music en este iPhone") {
            Text("Busca y reproduce una canción localmente con MusicKit. Esta función no envía nada al PC.")
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("Artista o canción", text: $localMusicQuery)
            Button("Autorizar Apple Music") {
                localAppleMusic.authorize()
            }
            .disabled(localAppleMusic.requestInProgress)
            Button("Buscar canciones") {
                localAppleMusic.search(term: localMusicQuery)
            }
            .buttonStyle(.borderedProminent)
            .disabled(
                localAppleMusic.requestInProgress ||
                    localMusicQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            )
            if !localAppleMusic.searchResults.isEmpty {
                Text("Elige una coincidencia")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ForEach(localAppleMusic.searchResults) { result in
                    Button {
                        localAppleMusic.play(result: result)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(result.title)
                            Text(result.artist)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .disabled(localAppleMusic.requestInProgress)
                }
            }
            HStack {
                Button("Anterior") {
                    localAppleMusic.previousTrack()
                }
                Button(localAppleMusic.isPlaying ? "Pausar" : "Reproducir") {
                    localAppleMusic.togglePlayback()
                }
                Button("Siguiente") {
                    localAppleMusic.nextTrack()
                }
            }
            .disabled(localAppleMusic.requestInProgress)
            Button("Detener") {
                localAppleMusic.stopPlayback()
            }
            .disabled(localAppleMusic.requestInProgress)
            if !localAppleMusic.currentTrack.isEmpty {
                Text(localAppleMusic.currentTrack)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(localAppleMusic.statusMessage)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var localMessagingSection: some View {
        Section("WhatsApp y Discord en este iPhone") {
            Text("Estos botones abren el destino mediante un enlace HTTPS. No envían mensajes ni inician llamadas automáticamente.")
                .font(.caption)
                .foregroundStyle(.secondary)

            TextField("Teléfono internacional de WhatsApp", text: $localWhatsAppPhone)
                .privacySensitive()
            TextField("Mensaje preparado", text: $localWhatsAppMessage, axis: .vertical)
                .lineLimit(1...4)
                .privacySensitive()
            HStack {
                Button("Abrir chat") {
                    guard let url = PipaMobileLocalIntegrationLinks.whatsappChatURL(phone: localWhatsAppPhone) else {
                        localIntegrationStatus = "Introduce un teléfono internacional válido."
                        return
                    }
                    openURL(url)
                    localIntegrationStatus = "Chat de WhatsApp abierto; no se ha preparado ni enviado ningún mensaje."
                }
                Button("Preparar mensaje") {
                    guard let url = PipaMobileLocalIntegrationLinks.whatsappComposeURL(
                        phone: localWhatsAppPhone,
                        message: localWhatsAppMessage
                    ) else {
                        localIntegrationStatus = "Revisa el teléfono y el mensaje."
                        return
                    }
                    openURL(url)
                    localIntegrationStatus = "Mensaje preparado en WhatsApp; pulsa Enviar manualmente."
                }
            }

            TextField("ID del canal de Discord", text: $localDiscordChannelID)
                .privacySensitive()
            TextField("ID del servidor (opcional)", text: $localDiscordGuildID)
                .privacySensitive()
            HStack {
                Button("Abrir canal") {
                    openLocalDiscordChannel(manualCall: false)
                }
                Button("Preparar llamada") {
                    openLocalDiscordChannel(manualCall: true)
                }
            }
            if !localIntegrationStatus.isEmpty {
                Text(localIntegrationStatus)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func openLocalDiscordChannel(manualCall: Bool) {
        let guild = localDiscordGuildID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = PipaMobileLocalIntegrationLinks.discordChannelURL(
            channelID: localDiscordChannelID,
            guildID: guild.isEmpty ? nil : guild
        ) else {
            localIntegrationStatus = "Introduce IDs de Discord válidos."
            return
        }
        openURL(url)
        localIntegrationStatus = manualCall
            ? "Canal de Discord abierto; pulsa Llamar manualmente."
            : "Canal de Discord abierto; no se ha iniciado ninguna llamada."
    }

    private var commandSection: some View {
        Section("Comando") {
            TextField("Escribe un comando para Pipα", text: $model.textCommand, axis: .vertical)
                .lineLimit(1...4)
#if os(iOS)
            HStack {
                Button(speechRecognizer.isListening ? "Parar dictado" : "Dictar comando") {
                    if speechRecognizer.isListening {
                        speechRecognizer.stop()
                    } else {
                        speechRecognizer.start()
                    }
                }
                .disabled(model.requestInProgress || model.pendingConfirmation != nil)
                if speechRecognizer.isListening {
                    Button("Cancelar", role: .cancel) {
                        speechRecognizer.cancel()
                    }
                }
                if speechRecognizer.isListening {
                    ProgressView()
                        .accessibilityLabel("Escuchando")
                }
            }
            Text("El dictado se procesa localmente y solo prepara el texto; no lo envía automáticamente.")
                .font(.caption2)
                .foregroundStyle(.secondary)
            if let speechError = speechRecognizer.errorMessage {
                Text(speechError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
#endif
            Button("Enviar comando") {
                model.sendTextCommand()
            }
            .disabled(sendCommandDisabled)

            if let pending = model.pendingConfirmation {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Confirmar acción")
                        .font(.headline)
                    Text(pending.summary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Rechazar", role: .cancel) {
                            model.resolveConfirmation(accepted: false)
                        }
                        Button("Aceptar") {
                            model.resolveConfirmation(accepted: true)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
                .accessibilityElement(children: .contain)
            }
        }
    }

    private var sendCommandDisabled: Bool {
        let baseDisabled = !model.isConnected ||
            model.requestInProgress ||
            model.pendingConfirmation != nil ||
            model.textCommand.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
#if os(iOS)
        return baseDisabled || speechRecognizer.isListening
#else
        return baseDisabled
#endif
    }

    private var catalogSection: some View {
        Section("Comandos disponibles") {
            if model.commands.isEmpty {
                Text("Conecta el iPhone para cargar el catálogo.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(model.commands) { command in
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(command.phrase)
                            Text(command.description)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            if command.requiresConfirmation {
                                Label("Requiere confirmación", systemImage: "hand.raised")
                                    .font(.caption2)
                                    .foregroundStyle(.orange)
                            }
                        }
                        Spacer(minLength: 4)
                        Button(commandCanExecuteDirectly(command) ? "Ejecutar" : "Usar") {
                            if commandCanExecuteDirectly(command) {
                                model.sendStructuredCommand(command, values: [:])
                            } else if command.placeholders.isEmpty {
                                model.useCommand(command)
                            } else {
                                commandToEdit = command
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }

    private func commandCanExecuteDirectly(_ command: PipaMobileCommand) -> Bool {
        command.supportsStructuredArguments && command.placeholders.isEmpty
    }
}
