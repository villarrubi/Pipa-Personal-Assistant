import Foundation
import PipaMobileCore
import SwiftUI
#if os(iOS)
import MusicKit
#endif

public struct PipaMobileAppleMusicResult: Identifiable, Equatable {
    public let id: String
    public let title: String
    public let artist: String

    public init(id: String, title: String, artist: String) {
        self.id = id
        self.title = title
        self.artist = artist
    }
}

/// Local Apple Music playback for the iPhone application.
///
/// This is deliberately separate from the Windows-agent `music_search` tool:
/// it uses Apple's supported MusicKit permission and player APIs on iOS, while
/// the remote PC action keeps its existing manual-selection boundary.
@available(iOS 16.0, macOS 13.0, *)
@MainActor
public final class PipaMobileAppleMusicController: ObservableObject {
    @Published public private(set) var isAuthorized = false
    @Published public private(set) var isPlaying = false
    @Published public private(set) var currentTrack = ""
    @Published public private(set) var searchResults: [PipaMobileAppleMusicResult] = []
    @Published public private(set) var statusMessage = "La reproducción local del iPhone está disponible al autorizar Apple Music."
    @Published public private(set) var requestInProgress = false

    #if os(iOS)
    private let player = SystemMusicPlayer.shared
    private var songs: [Song] = []
    #endif
    private var operationGeneration: UInt64 = 0

    public init() {}

    public var isNativePlaybackAvailable: Bool {
        #if os(iOS)
        return true
        #else
        return false
        #endif
    }

    /// Ask for Apple's media permission without starting playback.
    public func authorize() {
        #if os(iOS)
        guard !requestInProgress else { return }
        let generation = beginAsyncOperation()
        Task { [weak self] in
            guard let self else { return }
            defer { self.finishAsyncOperation(generation) }
            let status = await MusicAuthorization.request()
            guard self.operationGeneration == generation, !Task.isCancelled else { return }
            self.applyAuthorization(status)
        }
        #else
        statusMessage = "La reproducción local de Apple Music requiere iPhone."
        #endif
    }

    /// Search the Apple Music catalog and expose a small local result list.
    /// The query is bounded and never crosses the Windows-agent transport.
    public func search(term: String) {
        let query = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard PipaMobileTextPolicy.isSafeDisplayText(query, maxBytes: 200) else {
            statusMessage = "Escribe una búsqueda musical válida y acotada."
            return
        }
        #if os(iOS)
        guard !requestInProgress else { return }
        let generation = beginAsyncOperation()
        statusMessage = "Buscando en Apple Music…"
        Task { [weak self] in
            guard let self else { return }
            defer { self.finishAsyncOperation(generation) }
            do {
                let authorization = await MusicAuthorization.request()
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                guard authorization == .authorized else {
                    self.applyAuthorization(authorization)
                    return
                }
                self.isAuthorized = true

                var request = MusicCatalogSearchRequest(term: query, types: [Song.self])
                request.limit = 5
                let response = try await request.response()
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                let foundSongs = Array(response.songs)
                guard !foundSongs.isEmpty else {
                    self.songs = []
                    self.searchResults = []
                    self.statusMessage = "No se ha encontrado esa canción en Apple Music."
                    return
                }
                self.songs = foundSongs
                self.searchResults = foundSongs.map {
                    PipaMobileAppleMusicResult(
                        id: String(describing: $0.id),
                        title: Self.safeMusicText($0.title, fallback: "Canción"),
                        artist: Self.safeMusicText($0.artistName, fallback: "Artista desconocido")
                    )
                }
                self.statusMessage = "Elige una canción para reproducirla en este iPhone."
            } catch {
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                self.songs = []
                self.searchResults = []
                self.statusMessage = "No se pudo buscar en Apple Music."
            }
        }
        #else
        statusMessage = "La reproducción local de Apple Music requiere iPhone."
        #endif
    }

    /// Play the exact result selected in the local result list.
    public func play(result: PipaMobileAppleMusicResult) {
        #if os(iOS)
        guard isAuthorized else {
            authorize()
            return
        }
        guard PipaMobileTextPolicy.isSafeDisplayText(result.id, maxBytes: 200),
              let song = songs.first(where: { String(describing: $0.id) == result.id }) else {
            statusMessage = "La canción seleccionada ya no está disponible."
            return
        }
        guard !requestInProgress else { return }
        let generation = beginAsyncOperation()
        Task { [weak self] in
            guard let self else { return }
            defer { self.finishAsyncOperation(generation) }
            do {
                self.player.queue = [song]
                try await self.player.play()
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                let title = Self.safeMusicText(song.title, fallback: "Canción")
                let artist = Self.safeMusicText(song.artistName, fallback: "Artista desconocido")
                self.currentTrack = title
                self.isPlaying = true
                self.statusMessage = "Reproduciendo: \(title) — \(artist)"
            } catch {
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                self.statusMessage = "No se pudo reproducir la canción seleccionada."
            }
        }
        #else
        statusMessage = "La reproducción local de Apple Music requiere iPhone."
        #endif
    }

    public func togglePlayback() {
        #if os(iOS)
        guard isAuthorized else {
            authorize()
            return
        }
        guard !requestInProgress else { return }
        if player.state.playbackStatus == .playing {
            player.pause()
            isPlaying = false
            statusMessage = "Apple Music pausado."
        } else {
            let generation = beginAsyncOperation()
            Task { [weak self] in
                guard let self else { return }
                defer { self.finishAsyncOperation(generation) }
                do {
                    try await self.player.play()
                    guard self.operationGeneration == generation, !Task.isCancelled else { return }
                    self.isPlaying = true
                    self.statusMessage = "Apple Music reproduciendo."
                } catch {
                    guard self.operationGeneration == generation, !Task.isCancelled else { return }
                    self.statusMessage = "No se pudo reanudar Apple Music."
                }
            }
        }
        #else
        statusMessage = "La reproducción local de Apple Music requiere iPhone."
        #endif
    }

    public func nextTrack() {
        #if os(iOS)
        guard isAuthorized else {
            authorize()
            return
        }
        guard !requestInProgress else { return }
        let generation = beginAsyncOperation()
        Task { [weak self] in
            guard let self else { return }
            defer { self.finishAsyncOperation(generation) }
            do {
                try await self.player.skipToNextEntry()
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                self.isPlaying = true
                self.statusMessage = "Siguiente pista de Apple Music."
            } catch {
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                self.statusMessage = "No hay una siguiente pista disponible."
            }
        }
        #else
        statusMessage = "La reproducción local de Apple Music requiere iPhone."
        #endif
    }

    /// Start the previous entry in the local queue, if MusicKit exposes one.
    public func previousTrack() {
        #if os(iOS)
        guard isAuthorized else {
            authorize()
            return
        }
        guard !requestInProgress else { return }
        let generation = beginAsyncOperation()
        Task { [weak self] in
            guard let self else { return }
            defer { self.finishAsyncOperation(generation) }
            do {
                try await self.player.skipToPreviousEntry()
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                self.isPlaying = true
                self.statusMessage = "Pista anterior de Apple Music."
            } catch {
                guard self.operationGeneration == generation, !Task.isCancelled else { return }
                self.statusMessage = "No hay una pista anterior disponible."
            }
        }
        #else
        statusMessage = "La reproducción local de Apple Music requiere iPhone."
        #endif
    }

    /// Stop the local system player without changing the selected queue.
    public func stopPlayback() {
        #if os(iOS)
        guard isAuthorized else {
            authorize()
            return
        }
        guard !requestInProgress else { return }
        player.stop()
        isPlaying = false
        statusMessage = "Apple Music detenido."
        #else
        statusMessage = "La reproducción local de Apple Music requiere iPhone."
        #endif
    }

    public func refreshPlaybackState() {
        #if os(iOS)
        isPlaying = player.state.playbackStatus == .playing
        #endif
    }

    /// Drop search results and the displayed track when the app leaves the
    /// foreground.  This does not stop the system player: playback is an
    /// explicit user choice, while the result list is only ephemeral UI data.
    public func clearEphemeralState() {
        operationGeneration &+= 1
        requestInProgress = false
        #if os(iOS)
        songs = []
        #endif
        searchResults = []
        currentTrack = ""
    }

    private func beginAsyncOperation() -> UInt64 {
        operationGeneration &+= 1
        requestInProgress = true
        return operationGeneration
    }

    private func finishAsyncOperation(_ generation: UInt64) {
        if operationGeneration == generation {
            requestInProgress = false
        }
    }

    #if os(iOS)
    private static func safeMusicText(_ value: String, fallback: String) -> String {
        guard PipaMobileTextPolicy.isSafeDisplayText(value, maxBytes: 256) else {
            return fallback
        }
        return value
    }

    private func applyAuthorization(_ status: MusicAuthorization.Status) {
        isAuthorized = status == .authorized
        statusMessage = isAuthorized
            ? "Apple Music autorizado en este iPhone."
            : "Apple Music necesita permiso para buscar y reproducir."
    }
    #endif
}
