import Foundation

/// Pure Wake-on-LAN packet construction shared by the mobile UI and its tests.
///
/// The packet never contains a server credential and is not sent through the
/// Pipa agent. The caller decides separately whether a local-network send is
/// appropriate and must keep the final action behind a visible confirmation.
public enum PipaMobileWakeOnLan {
    public static let packetSize = 102

    /// Return a canonical colon-separated MAC address or nil for an unsafe
    /// target. Multicast, all-zero and broadcast addresses are not valid PC
    /// wake targets.
    public static func normalizeMAC(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        let scalars = Array(trimmed.unicodeScalars)
        guard scalars.count == 17 else { return nil }

        let separator = scalars[2].value
        guard separator == 0x3A || separator == 0x2D else { return nil }

        var bytes: [UInt8] = []
        bytes.reserveCapacity(6)
        for index in 0..<6 {
            let offset = index * 3
            if index < 5, scalars[offset + 2].value != separator {
                return nil
            }
            guard let high = hexValue(scalars[offset].value),
                  let low = hexValue(scalars[offset + 1].value) else {
                return nil
            }
            bytes.append((high << 4) | low)
        }

        guard !bytes.allSatisfy({ $0 == 0x00 }),
              !bytes.allSatisfy({ $0 == 0xFF }),
              let first = bytes.first,
              (first & 0x01) == 0 else {
            return nil
        }
        return bytes.map { String(format: "%02X", $0) }.joined(separator: ":")
    }

    /// Build the standard six-FF + sixteen-MAC magic packet.
    public static func magicPacket(for mac: String) -> Data? {
        guard let normalized = normalizeMAC(mac) else { return nil }
        let parts = normalized.split(separator: ":")
        let bytes = parts.compactMap { UInt8($0, radix: 16) }
        guard parts.count == 6, bytes.count == 6 else {
            return nil
        }

        var packet = Data(repeating: 0xFF, count: 6)
        for _ in 0..<16 {
            packet.append(contentsOf: bytes)
        }
        return packet.count == packetSize ? packet : nil
    }

    private static func hexValue(_ scalar: UInt32) -> UInt8? {
        switch scalar {
        case 0x30...0x39:
            return UInt8(scalar - 0x30)
        case 0x41...0x46:
            return UInt8(scalar - 0x41 + 10)
        case 0x61...0x66:
            return UInt8(scalar - 0x61 + 10)
        default:
            return nil
        }
    }
}
