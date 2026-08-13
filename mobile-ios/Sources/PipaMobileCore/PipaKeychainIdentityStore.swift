import CryptoKit
import Foundation
import Security

public final class PipaKeychainIdentityStore {
    private let service: String

    public init(service: String = "com.pipa.mobile.ed25519") {
        self.service = service
    }

    public func loadOrCreate(identityID: String) throws -> PipaMobileIdentity {
        guard PipaMobileIdentity.isValidIdentifier(identityID) else {
            throw PipaMobileError.invalidIdentity
        }
        if let rawKey = try load(identityID: identityID) {
            do {
                return try PipaMobileIdentity(
                    identityID: identityID,
                    privateKey: try Curve25519.Signing.PrivateKey(rawRepresentation: rawKey)
                )
            } catch {
                throw PipaMobileError.invalidIdentity
            }
        }

        let identity = try PipaMobileIdentity.generate(identityID: identityID)
        let rawKey = identity.privateKey.rawRepresentation
        try save(rawKey, identityID: identityID)
        return identity
    }

    public func delete(identityID: String) throws {
        guard PipaMobileIdentity.isValidIdentifier(identityID) else {
            throw PipaMobileError.invalidIdentity
        }
        let query = baseQuery(identityID: identityID)
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw PipaKeychainError(status: status)
        }
    }

    private func load(identityID: String) throws -> Data? {
        var query = baseQuery(identityID: identityID)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess, let data = result as? Data, data.count == 32 else {
            throw PipaKeychainError(status: status)
        }
        return data
    }

    private func save(_ data: Data, identityID: String) throws {
        var query = baseQuery(identityID: identityID)
        query[kSecValueData as String] = data
#if os(iOS) || os(tvOS) || os(watchOS)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
#endif
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw PipaKeychainError(status: status)
        }
    }

    private func baseQuery(identityID: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: identityID,
            kSecAttrSynchronizable as String: false,
        ]
    }
}

public struct PipaKeychainError: Error {
    public let status: OSStatus
}
