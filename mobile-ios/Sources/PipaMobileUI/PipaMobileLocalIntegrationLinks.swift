import Foundation
import PipaMobileCore

/// Builds the small set of HTTPS links that the iPhone can hand to the
/// installed WhatsApp or Discord app (or to Safari when the app is absent).
///
/// This helper deliberately does not use private app APIs or UI automation.
/// Opening a link prepares the destination only: WhatsApp still needs a human
/// tap on Send and Discord still needs a human tap to start a call.
public enum PipaMobileLocalIntegrationLinks {

    public static func whatsappComposeURL(phone: String, message: String) -> URL? {
        guard let normalizedPhone = PipaMobileDestinationPolicy.normalizePhone(phone),
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
        guard let normalizedPhone = PipaMobileDestinationPolicy.normalizePhone(phone) else { return nil }

        var components = URLComponents()
        components.scheme = "https"
        components.host = "wa.me"
        components.path = "/\(normalizedPhone)"
        return components.url
    }

    public static func discordChannelURL(channelID: String, guildID: String? = nil) -> URL? {
        guard let channel = PipaMobileDestinationPolicy.normalizeSnowflake(channelID),
              let guild = normalizeGuild(guildID) else {
            return nil
        }

        var components = URLComponents()
        components.scheme = "https"
        components.host = "discord.com"
        components.path = "/channels/\(guild)/\(channel)"
        return components.url
    }

    private static func normalizeGuild(_ value: String?) -> String? {
        guard let value else { return "@me" }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "@me" : PipaMobileDestinationPolicy.normalizeSnowflake(trimmed)
    }
}
