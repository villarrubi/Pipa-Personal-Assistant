import Foundation

/// Canonical, non-sensitive destination validation shared by mobile surfaces.
///
/// The Windows agent applies the same rules before opening WhatsApp or Discord.
/// Keeping the policy in the Core target prevents the local-link and structured
/// command forms from accepting different spellings of the same destination.
public enum PipaMobileDestinationPolicy {
    private static let whatsappPhoneCharacters = CharacterSet(charactersIn: "0123456789+ ()-.")

    public static func normalizePhone(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              trimmed.unicodeScalars.allSatisfy({ whatsappPhoneCharacters.contains($0) }) else {
            return nil
        }

        let withoutFormatting = trimmed.filter { !" ().-".contains($0) }
        let digits: String
        if withoutFormatting.first == "+" {
            digits = String(withoutFormatting.dropFirst())
        } else {
            digits = withoutFormatting
        }
        guard (7...15).contains(digits.utf8.count),
              digits.first != "0",
              digits.utf8.allSatisfy({ (0x30...0x39).contains($0) }) else {
            return nil
        }
        return digits
    }

    public static func normalizeSnowflake(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (17...20).contains(trimmed.utf8.count),
              trimmed.first != "0",
              trimmed.utf8.allSatisfy({ (0x30...0x39).contains($0) }) else {
            return nil
        }
        return trimmed
    }
}
