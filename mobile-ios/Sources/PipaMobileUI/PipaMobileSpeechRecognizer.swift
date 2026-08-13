#if os(iOS)
import AVFoundation
import Speech
import SwiftUI

@available(iOS 16.0, *)
@MainActor
public final class PipaMobileSpeechRecognizer: NSObject, ObservableObject {
    @Published public private(set) var isListening = false
    @Published public private(set) var transcript = ""
    @Published public private(set) var errorMessage: String?

    private let recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?

    public override init() {
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: "es-ES"))
        super.init()
    }

    public func start() {
        guard !isListening else { return }
        transcript = ""
        errorMessage = nil
        requestMicrophonePermission()
    }

    public func stop() {
        finish(clearTranscript: false)
    }

    public func cancel() {
        finish(clearTranscript: true)
    }

    private func requestMicrophonePermission() {
        let session = AVAudioSession.sharedInstance()
        switch session.recordPermission {
        case .granted:
            requestSpeechPermission()
        case .denied:
            fail("El micrófono está bloqueado; puedes habilitarlo en Ajustes.")
        case .undetermined:
            session.requestRecordPermission { [weak self] granted in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    if granted {
                        self.requestSpeechPermission()
                    } else {
                        self.fail("No se concedió permiso para usar el micrófono.")
                    }
                }
            }
        @unknown default:
            fail("No se pudo determinar el permiso del micrófono.")
        }
    }

    private func requestSpeechPermission() {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized:
            beginRecognition()
        case .denied:
            fail("El reconocimiento de voz está bloqueado; puedes habilitarlo en Ajustes.")
        case .restricted:
            fail("El reconocimiento de voz está restringido en este dispositivo.")
        case .notDetermined:
            SFSpeechRecognizer.requestAuthorization { [weak self] status in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    if status == .authorized {
                        self.beginRecognition()
                    } else {
                        self.fail("No se concedió permiso para el reconocimiento de voz.")
                    }
                }
            }
        @unknown default:
            fail("No se pudo determinar el permiso de reconocimiento de voz.")
        }
    }

    private func beginRecognition() {
        guard let recognizer else {
            fail("El reconocimiento en español no está disponible en este iPhone.")
            return
        }
        guard recognizer.isAvailable else {
            fail("El reconocimiento de voz no está disponible ahora.")
            return
        }
        guard recognizer.supportsOnDeviceRecognition else {
            fail("El reconocimiento local no está disponible en este iPhone.")
            return
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = true
        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            fail("La entrada de audio no está disponible.")
            return
        }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            inputNode.removeTap(onBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak request] buffer, _ in
                request?.append(buffer)
            }
            audioEngine.prepare()
            recognitionRequest = request
            recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
                let text = result?.bestTranscription.formattedString
                let isFinal = result?.isFinal ?? false
                let failed = error != nil
                Task { @MainActor [weak self] in
                    self?.receive(text: text, isFinal: isFinal, failed: failed)
                }
            }
            try audioEngine.start()
            isListening = true
        } catch {
            finish(clearTranscript: false)
            fail("No se pudo iniciar el dictado local.")
        }
    }

    private func receive(text: String?, isFinal: Bool, failed: Bool) {
        if let text, !text.isEmpty {
            transcript = bounded(text)
        }
        if failed || isFinal {
            finish(clearTranscript: false)
        }
    }

    private func finish(clearTranscript: Bool) {
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: .notifyOthersOnDeactivation
        )
        isListening = false
        if clearTranscript {
            transcript = ""
        }
    }

    private func fail(_ message: String) {
        finish(clearTranscript: false)
        errorMessage = message
    }

    private func bounded(_ value: String) -> String {
        var result = ""
        for character in value {
            let candidate = result + String(character)
            if candidate.utf8.count > 4000 {
                break
            }
            result = candidate
        }
        return result
    }
}
#endif
