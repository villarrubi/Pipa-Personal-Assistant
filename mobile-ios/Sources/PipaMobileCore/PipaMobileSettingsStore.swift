import Foundation
import Security

/// Non-secret connection settings pinned to this device.
///
/// The server public key is trust material, not a credential, but it is still
/// kept in a non-synchronizable Keychain item so a backup or second device
/// cannot silently change the endpoint configuration.
public struct PipaMobileSettings: Codable, Equatable, Sendable {
    public let host: String
    public let port: String
    public let serverID: String
    public let serverPublicKey: String
    public let identityID: String

    public init(
        host: String,
        port: String,
        serverID: String,
        serverPublicKey: String,
        identityID: String
    ) {
        self.host = host
        self.port = port
        self.serverID = serverID
        self.serverPublicKey = serverPublicKey
        self.identityID = identityID
    }

    /// Validate values before they enter or leave the device-local Keychain.
    ///
    /// The first screen intentionally allows a partial configuration while
    /// the user is copying the agent fingerprint, so `host` and
    /// `serverPublicKey` may still be empty. Any value that is present must
    /// nevertheless already satisfy the same endpoint and identity contract
    /// used by the live TCP client.
    public func validateForStorage() throws {
        guard Self.isSafeStorageText(host, maximumBytes: 253),
              Self.isSafeStorageText(port, maximumBytes: 5),
              Self.isSafeStorageText(serverID, maximumBytes: 128),
              Self.isSafeStorageText(serverPublicKey, maximumBytes: 128),
              Self.isSafeStorageText(identityID, maximumBytes: 128),
              PipaMobileIdentity.isValidIdentifier(serverID),
              PipaMobileIdentity.isValidIdentifier(identityID) else {
            throw PipaMobileError.invalidMessage
        }

        if !host.isEmpty {
            guard PipaMobileTCPClient.isAllowedHost(host) else {
                throw PipaMobileError.invalidMessage
            }
        }
        if !port.isEmpty {
            guard let value = UInt16(port), value != 0 else {
                throw PipaMobileError.invalidMessage
            }
        }
        if !serverPublicKey.isEmpty {
            guard (try? PipaMobileIdentity.decodePublicKeyBase64URL(serverPublicKey)) != nil else {
                throw PipaMobileError.invalidMessage
            }
        }
    }

    private static func isSafeStorageText(_ value: String, maximumBytes: Int) -> Bool {
        value.utf8.count <= maximumBytes && !PipaMobileTextPolicy.containsDisplayControl(value)
    }
}

public protocol PipaMobileSettingsStoring {
    func load() throws -> PipaMobileSettings?
    func save(_ settings: PipaMobileSettings) throws
    func delete() throws
}

public final class PipaMobileSettingsStore: PipaMobileSettingsStoring {
    private static let maximumEncodedBytes = 4096
    private let service: String
    private let account: String

    public init(
        service: String = "com.pipa.mobile.settings",
        account: String = "default"
    ) {
        self.service = service
        self.account = account
    }

    public func load() throws -> PipaMobileSettings? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess, let data = result as? Data,
              data.count <= Self.maximumEncodedBytes else {
            throw PipaKeychainError(status: status)
        }
        do {
            let settings = try JSONDecoder().decode(PipaMobileSettings.self, from: data)
            try settings.validateForStorage()
            return settings
        } catch {
            throw PipaMobileError.invalidMessage
        }
    }

    public func save(_ settings: PipaMobileSettings) throws {
        try settings.validateForStorage()
        let data: Data
        do {
            data = try JSONEncoder().encode(settings)
        } catch {
            throw PipaMobileError.invalidMessage
        }
        guard data.count <= Self.maximumEncodedBytes else {
            throw PipaMobileError.payloadTooLarge
        }

        var updateAttributes: [String: Any] = [kSecValueData as String: data]
#if os(iOS) || os(tvOS) || os(watchOS)
        updateAttributes[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
#endif
        let updateStatus = SecItemUpdate(
            baseQuery() as CFDictionary,
            updateAttributes as CFDictionary
        )
        if updateStatus == errSecSuccess {
            return
        }
        guard updateStatus == errSecItemNotFound else {
            throw PipaKeychainError(status: updateStatus)
        }

        var query = baseQuery()
        query[kSecValueData as String] = data
#if os(iOS) || os(tvOS) || os(watchOS)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
#endif
        let addStatus = SecItemAdd(query as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw PipaKeychainError(status: addStatus)
        }
    }

    public func delete() throws {
        let status = SecItemDelete(baseQuery() as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw PipaKeychainError(status: status)
        }
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrSynchronizable as String: false,
        ]
    }
}
