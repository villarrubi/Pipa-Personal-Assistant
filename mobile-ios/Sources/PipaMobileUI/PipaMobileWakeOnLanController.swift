import Foundation
import Network
import PipaMobileCore
import SwiftUI

/// Sends a bounded, local-only Wake-on-LAN packet from the iPhone.
///
/// The destination is fixed to the IPv4 broadcast address and UDP port 9; no
/// host, URL, credential or agent transport can be supplied by the caller.
/// The caller must show a visible confirmation before invoking `wake(mac:)`.
@available(iOS 16.0, macOS 13.0, *)
@MainActor
public final class PipaMobileWakeOnLanController: ObservableObject {
    @Published public private(set) var requestInProgress = false
    @Published public private(set) var statusMessage =
        "Introduce la MAC del PC para despertarlo en la red local."

    private var connection: NWConnection?
    private var packet: Data?
    private var operationID = 0
    private var sendStarted = false

    public init() {}

    /// Validate a destination before showing the confirmation dialog.
    @discardableResult
    public func validate(mac: String) -> Bool {
        guard PipaMobileWakeOnLan.magicPacket(for: mac) != nil else {
            statusMessage = "Introduce una MAC unicast válida."
            return false
        }
        return true
    }

    public func wake(mac: String) {
        guard let packet = PipaMobileWakeOnLan.magicPacket(for: mac), validate(mac: mac) else { return }
        guard !requestInProgress else { return }

#if os(iOS)
        guard let port = NWEndpoint.Port(rawValue: 9) else {
            statusMessage = "Wake-on-LAN no está disponible."
            return
        }

        operationID &+= 1
        let currentOperation = operationID
        requestInProgress = true
        statusMessage = "Enviando Wake-on-LAN por la red local…"
        self.packet = packet
        sendStarted = false

        let parameters = NWParameters.udp
        parameters.allowLocalEndpointReuse = true
        let connection = NWConnection(
            host: NWEndpoint.Host("255.255.255.255"),
            port: port,
            using: parameters
        )
        self.connection = connection
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            guard let connection else { return }
            DispatchQueue.main.async { [weak self, weak connection] in
                guard let connection else { return }
                self?.handle(
                    state: state,
                    operationID: currentOperation,
                    connection: connection
                )
            }
        }
        connection.start(queue: DispatchQueue(label: "com.pipa.wake-on-lan"))

        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self, weak connection] in
            guard let connection else { return }
            guard let self, self.operationID == currentOperation,
                  self.connection === connection else { return }
            self.finish(
                operationID: currentOperation,
                connection: connection,
                success: false
            )
        }
#else
        statusMessage = "Wake-on-LAN desde la app requiere iPhone."
#endif
    }

    /// Stop an in-flight local broadcast when the screen goes away.
    public func cancel() {
        guard requestInProgress else { return }
        operationID &+= 1
        let connection = self.connection
        self.connection = nil
        packet = nil
        requestInProgress = false
        connection?.cancel()
        statusMessage = "Wake-on-LAN cancelado."
    }

#if os(iOS)
    private func handle(
        state: NWConnection.State,
        operationID: Int,
        connection: NWConnection
    ) {
        guard self.operationID == operationID, self.connection === connection else { return }

        switch state {
        case .ready:
            guard !sendStarted, let packet else { return }
            sendStarted = true
            connection.send(content: packet, completion: .contentProcessed { [weak self, weak connection] error in
                DispatchQueue.main.async { [weak self, weak connection] in
                    guard let self, let connection,
                          self.operationID == operationID,
                          self.connection === connection else { return }
                    self.finish(
                        operationID: operationID,
                        connection: connection,
                        success: error == nil
                    )
                }
            })
        case .failed:
            finish(operationID: operationID, connection: connection, success: false)
        case .cancelled:
            if requestInProgress {
                finish(operationID: operationID, connection: connection, success: false)
            }
        default:
            break
        }
    }

    private func finish(
        operationID: Int,
        connection: NWConnection,
        success: Bool
    ) {
        guard self.operationID == operationID, self.connection === connection else { return }
        self.connection = nil
        packet = nil
        requestInProgress = false
        connection.cancel()
        statusMessage = success
            ? "Paquete Wake-on-LAN enviado en la red local."
            : "No se pudo enviar Wake-on-LAN en la red local."
    }
#endif
}
