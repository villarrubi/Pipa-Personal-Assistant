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
        requestInProgress = true
        Task { [weak self] in
            defer { self?.requestInProgress = false }
            let status = await MusicAuthorization.request()
            guard let self else { return }
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
        requestInProgress = true
        statusMessage = "Buscando en Apple Music…"
        Task { [weak self] in
            guard let self else { return }
            defer { self.requestInProgress = false }
            do {
                let authorization = await MusicAuthorization.request()
                guard authorization == .authorized else {
                    self.applyAuthorization(authorization)
                    return
                }
                self.isAuthorized = true

                var request = MusicCatalogSearchRequest(term: query, types: [Song.self])
                request.limit = 5
                let response = try await request.response()
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
        requestInProgress = true
        Task { [weak self] in
            guard let self else { return }
            defer { self.requestInProgress = false }
            do {
                self.player.queue = [song]
                try await self.player.play()
                let title = Self.safeMusicText(song.title, fallback: "Canción")
                let artist = Self.safeMusicText(song.artistName, fallback: "Artista desconocido")
                self.currentTrack = title
                self.isPlaying = true
                self.statusMessage = "Reproduciendo: \(title) — \(artist)"
            } catch {
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
        if player.state.playbackStatus == .playing {
            player.pause()
            isPlaying = false
            statusMessage = "Apple Music pausado."
        } else {
            guard !requestInProgress else { return }
            requestInProgress = true
            Task { [weak self] in
                guard let self else { return }
                defer { self.requestInProgress = false }
                do {
                    try await self.player.play()
                    self.isPlaying = true
                    self.statusMessage = "Apple Music reproduciendo."
                } catch {
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
        requestInProgress = true
        Task { [weak self] in
            guard let self else { return }
            defer { self.requestInProgress = false }
            do {
                try await self.player.skipToNextEntry()
                self.isPlaying = true
                self.statusMessage = "Siguiente pista de Apple Music."
            } catch {
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
        requestInProgress = true
        Task { [weak self] in
            guard let self else { return }
            defer { self.requestInProgress = false }
            do {
                try await self.player.skipToPreviousEntry()
                self.isPlaying = true
                self.statusMessage = "Pista anterior de Apple Music."
            } catch {
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
