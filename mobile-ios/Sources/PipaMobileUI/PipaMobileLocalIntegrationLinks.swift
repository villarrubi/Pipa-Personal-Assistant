import Foundation
import PipaMobileCore

/// Builds the small set of HTTPS links that the iPhone can hand to the
/// installed WhatsApp or Discord app (or to Safari when the app is absent).
///
/// This helper deliberately does not use private app APIs or UI automation.
/// Opening a link prepares the destination only: WhatsApp still needs a human
/// tap on Send and Discord still needs a human tap to start a call.
public enum PipaMobileLocalIntegrationLinks {
    private static let whatsappPhoneCharacters = CharacterSet(charactersIn: "0123456789+ ()-.")

    public static func whatsappComposeURL(phone: String, message: String) -> URL? {
        guard let normalizedPhone = normalizePhone(phone),
              PipaMobileTextPolicy.isSafeMessageText(message, maxBytes: 3800) else {
            return nil
        }

        var components = URLComponents()
        components.scheme = "https"
        components.host = "wa.me"
        components.path = "/\(normalizedPhone)"
        components.queryItems = [URLQueryItem(name: "text", value: message)]
        return components.url
    }

    public static func whatsappChatURL(phone: String) -> URL? {
        guard let normalizedPhone = normalizePhone(phone) else { return nil }

        var components = URLComponents()
        components.scheme = "https"
        components.host = "wa.me"
        components.path = "/\(normalizedPhone)"
        return components.url
    }

    public static func discordChannelURL(channelID: String, guildID: String? = nil) -> URL? {
        guard let channel = normalizeSnowflake(channelID),
              let guild = normalizeGuild(guildID) else {
            return nil
        }

        var components = URLComponents()
        components.scheme = "https"
        components.host = "discord.com"
        components.path = "/channels/\(guild)/\(channel)"
        return components.url
    }

    private static func normalizePhone(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              trimmed.unicodeScalars.allSatisfy({ whatsappPhoneCharacters.contains($0) }) else {
            return nil
        }

        let withoutFormatting = trimmed.filter { !" ()-.".contains($0) }
        let digits: String
        if withoutFormatting.first == "+" {
            digits = String(withoutFormatting.dropFirst())
        } else {
            digits = withoutFormatting
        }
        guard (7...15).contains(digits.utf8.count),
              digits.utf8.allSatisfy({ (0x30...0x39).contains($0) }) else {
            return nil
        }
        return digits
    }

    private static func normalizeSnowflake(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (17...20).contains(trimmed.utf8.count),
              trimmed.utf8.allSatisfy({ (0x30...0x39).contains($0) }) else {
            return nil
        }
        return trimmed
    }

    private static func normalizeGuild(_ value: String?) -> String? {
        guard let value else { return "@me" }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "@me" : normalizeSnowflake(trimmed)
    }
}
