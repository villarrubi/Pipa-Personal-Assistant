import Foundation
import PipaMobileCore

/// Builds the small set of HTTPS links that the iPhone can hand to Safari or the
/// installed WhatsApp or Discord app (or to Safari when an app is absent).
///
/// This helper deliberately does not use private app APIs or UI automation.
/// Opening a link prepares the destination only: WhatsApp still needs a human
/// tap on Send and Discord still needs a human tap to start a call.
public enum PipaMobileLocalIntegrationLinks {

    public static func webSearchURL(query: String) -> URL? {
        let normalizedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard PipaMobileTextPolicy.isSafeDisplayText(normalizedQuery, maxBytes: 200) else {
            return nil
        }

        return httpsURL(
            host: "www.google.com",
            path: "/search",
            queryItems: [URLQueryItem(name: "q", value: normalizedQuery)]
        )
    }

    public static func whatsappComposeURL(phone: String, message: String) -> URL? {
        guard let normalizedPhone = PipaMobileDestinationPolicy.normalizePhone(phone),
              PipaMobileTextPolicy.isSafeMessageText(message, maxBytes: 3800) else {
            return nil
        }

        return httpsURL(
            host: "wa.me",
            path: "/\(normalizedPhone)",
            queryItems: [URLQueryItem(name: "text", value: message)]
        )
    }

    public static func whatsappChatURL(phone: String) -> URL? {
        guard let normalizedPhone = PipaMobileDestinationPolicy.normalizePhone(phone) else { return nil }

        return httpsURL(host: "wa.me", path: "/\(normalizedPhone)")
    }

    public static func discordChannelURL(channelID: String, guildID: String? = nil) -> URL? {
        guard let channel = PipaMobileDestinationPolicy.normalizeSnowflake(channelID),
              let guild = normalizeGuild(guildID) else {
            return nil
        }

        return httpsURL(host: "discord.com", path: "/channels/\(guild)/\(channel)")
    }

    private static func normalizeGuild(_ value: String?) -> String? {
        guard let value else { return "@me" }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "@me" : PipaMobileDestinationPolicy.normalizeSnowflake(trimmed)
    }

    /// Build only the fixed HTTPS destinations owned by this module.
    ///
    /// Keeping the scheme and host in one helper makes it harder for a future
    /// local integration to accidentally accept a custom scheme or a caller-
    /// supplied host. Dynamic values are restricted to paths and query items
    /// after their caller-specific validation.
    private static func httpsURL(
        host: String,
        path: String,
        queryItems: [URLQueryItem] = []
    ) -> URL? {
        var components = URLComponents()
        components.scheme = "https"
        components.host = host
        components.path = path
        components.queryItems = queryItems.isEmpty ? nil : queryItems
        guard let url = components.url,
              url.scheme == "https",
              url.host == host else {
            return nil
        }
        return url
    }
}
