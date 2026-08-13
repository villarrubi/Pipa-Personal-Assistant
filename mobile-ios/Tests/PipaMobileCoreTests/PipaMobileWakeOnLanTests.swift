import XCTest
@testable import PipaMobileCore

final class PipaMobileWakeOnLanTests: XCTestCase {
    func testNormalizesAndBuildsTheStandardMagicPacket() throws {
        XCTAssertEqual(
            PipaMobileWakeOnLan.normalizeMAC("aa-bb-cc-dd-ee-f0"),
            "AA:BB:CC:DD:EE:F0"
        )

        let packet = try XCTUnwrap(
            PipaMobileWakeOnLan.magicPacket(for: "AA:BB:CC:DD:EE:F0")
        )
        XCTAssertEqual(packet.count, PipaMobileWakeOnLan.packetSize)
        XCTAssertEqual(Array(packet.prefix(6)), Array(repeating: 0xFF, count: 6))
        for repeatIndex in 0..<16 {
            let start = 6 + (repeatIndex * 6)
            XCTAssertEqual(
                Array(packet[start..<(start + 6)]),
                [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xF0]
            )
        }
    }

    func testRejectsInvalidOrNonUnicastMACAddresses() {
        let invalid = [
            "00:00:00:00:00:00",
            "FF:FF:FF:FF:FF:FF",
            "01:BB:CC:DD:EE:F0",
            "AA:BB:CC:DD:EE",
            "AA:BB-CC:DD:EE:F0",
            "AA:BB:CC:DD:EE:GG",
            "ＡＡ:BB:CC:DD:EE:F0",
        ]

        for value in invalid {
            XCTAssertNil(PipaMobileWakeOnLan.magicPacket(for: value), value)
        }
    }
}
