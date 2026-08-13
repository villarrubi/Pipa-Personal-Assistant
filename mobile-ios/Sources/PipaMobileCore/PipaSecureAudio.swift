import Foundation

/// The bounded binary audio profile shared with `windows-agent/secure_audio.py`.
/// It is a transport primitive only: the app does not capture or announce
/// audio until the physical board, consent indicator and STT policy are ready.
public enum PipaSecureAudioContract {
    public static let protocolVersion = 2
    public static let sampleRate = 16_000
    public static let channels = 1
    public static let bitsPerSample = 16
    public static let maxChunkBytes = 4_096
    public static let maxChunks = 64
    public static let maxStreamBytes = maxChunkBytes * maxChunks
    public static let aadPrefix = Data("pipa/audio/v2\0".utf8)

    static let recordFields: Set<String> = ["ciphertext", "protocol_version", "sequence", "session_id"]
    static let audioFields: Set<String> = [
        "audio_protocol_version",
        "bits_per_sample",
        "channels",
        "chunk_index",
        "final",
        "sample_rate",
        "stream_id",
    ]

    static func validStreamID(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 64 && value.utf8.allSatisfy { byte in
            (byte >= 0x41 && byte <= 0x5A) ||
                (byte >= 0x61 && byte <= 0x7A) ||
                (byte >= 0x30 && byte <= 0x39) ||
                byte == 0x2D || byte == 0x5F
        }
    }

    static func metadata(streamID: String, chunkIndex: Int, final: Bool) -> [String: Any] {
        [
            "audio_protocol_version": protocolVersion,
            "bits_per_sample": bitsPerSample,
            "channels": channels,
            "chunk_index": chunkIndex,
            "final": final,
            "sample_rate": sampleRate,
            "stream_id": streamID,
        ]
    }

    static func additionalData(metadata: [String: Any]) throws -> Data {
        aadPrefix + (try PipaMobileCodec.canonicalJSON(metadata))
    }
}

/// Sequential sender for encrypted PCM chunks. It stores no samples.
public final class PipaSecureAudioSender {
    private let layer: PipaSecureRecordLayer
    private let streamID: String
    private var nextChunk = 0
    private var streamBytes = 0
    private var finished = false

    public init(layer: PipaSecureRecordLayer, streamID: String) throws {
        guard PipaSecureAudioContract.validStreamID(streamID) else {
            throw PipaMobileError.invalidAudioFrame
        }
        self.layer = layer
        self.streamID = streamID
    }

    public func sealChunk(samples: Data, final: Bool) throws -> [String: Any] {
        guard !finished,
              nextChunk < PipaSecureAudioContract.maxChunks,
              !samples.isEmpty,
              samples.count <= PipaSecureAudioContract.maxChunkBytes,
              samples.count % 2 == 0,
              streamBytes + samples.count <= PipaSecureAudioContract.maxStreamBytes else {
            throw PipaMobileError.invalidAudioFrame
        }
        if nextChunk == PipaSecureAudioContract.maxChunks - 1 && !final {
            throw PipaMobileError.invalidAudioFrame
        }
        let metadata = PipaSecureAudioContract.metadata(
            streamID: streamID,
            chunkIndex: nextChunk,
            final: final
        )
        let frame = try layer.sealBinary(
            payload: samples,
            additionalData: try PipaSecureAudioContract.additionalData(metadata: metadata)
        )
        nextChunk += 1
        streamBytes += samples.count
        finished = final
        return frame.merging(metadata, uniquingKeysWith: { _, new in new })
    }

    public func cancel() {
        finished = true
        nextChunk = 0
        streamBytes = 0
    }
}

/// Ordered receiver for one encrypted stream. Invalid frames close the record
/// layer, forcing a fresh authenticated session instead of resynchronizing.
public final class PipaSecureAudioReceiver {
    private let layer: PipaSecureRecordLayer
    private var streamID: String?
    private var nextChunk = 0
    private var streamBytes = 0
    private var finished = false

    public init(layer: PipaSecureRecordLayer) {
        self.layer = layer
    }

    public var isComplete: Bool { finished }
    public var streamByteCount: Int { streamBytes }

    public func open(frame: [String: Any]) throws -> Data {
        do {
            guard Set(frame.keys) == PipaSecureAudioContract.recordFields.union(
                PipaSecureAudioContract.audioFields
            ),
            let metadata = try validateMetadata(frame),
            !finished,
            metadata.chunkIndex == nextChunk else {
                throw PipaMobileError.invalidAudioFrame
            }
            if let streamID {
                guard metadata.streamID == streamID else { throw PipaMobileError.invalidAudioFrame }
            } else {
                guard metadata.chunkIndex == 0 else { throw PipaMobileError.invalidAudioFrame }
                streamID = metadata.streamID
            }

            let samples = try layer.openBinary(
                frame: frame,
                additionalData: try PipaSecureAudioContract.additionalData(metadata: metadata.values)
            )
            guard !samples.isEmpty,
                  samples.count <= PipaSecureAudioContract.maxChunkBytes,
                  samples.count % 2 == 0,
                  streamBytes + samples.count <= PipaSecureAudioContract.maxStreamBytes else {
                throw PipaMobileError.invalidAudioFrame
            }
            nextChunk += 1
            streamBytes += samples.count
            finished = metadata.isFinal
            return samples
        } catch let error as PipaMobileError {
            discardAndClose()
            throw error
        } catch {
            discardAndClose()
            throw PipaMobileError.invalidAudioFrame
        }
    }

    public func cancel() {
        streamID = nil
        nextChunk = 0
        streamBytes = 0
        finished = false
    }

    public func close() {
        cancel()
        layer.close()
    }

    private func discardAndClose() {
        cancel()
        layer.close()
    }

    private struct ValidatedMetadata {
        let values: [String: Any]
        let streamID: String
        let chunkIndex: Int
        let isFinal: Bool
    }

    private func validateMetadata(_ frame: [String: Any]) throws -> ValidatedMetadata? {
        guard let version = frame["audio_protocol_version"] as? Int,
              version == PipaSecureAudioContract.protocolVersion,
              let bits = frame["bits_per_sample"] as? Int,
              bits == PipaSecureAudioContract.bitsPerSample,
              let channels = frame["channels"] as? Int,
              channels == PipaSecureAudioContract.channels,
              let sampleRate = frame["sample_rate"] as? Int,
              sampleRate == PipaSecureAudioContract.sampleRate,
              let chunkIndex = frame["chunk_index"] as? Int,
              (0..<PipaSecureAudioContract.maxChunks).contains(chunkIndex),
              let isFinal = frame["final"] as? Bool,
              let streamID = frame["stream_id"] as? String,
              PipaSecureAudioContract.validStreamID(streamID) else {
            throw PipaMobileError.invalidAudioFrame
        }
        return ValidatedMetadata(
            values: PipaSecureAudioContract.metadata(
                streamID: streamID,
                chunkIndex: chunkIndex,
                final: isFinal
            ),
            streamID: streamID,
            chunkIndex: chunkIndex,
            isFinal: isFinal
        )
    }
}
