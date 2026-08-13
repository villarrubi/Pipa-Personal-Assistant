#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include <stdint.h>

#include "device_identity.h"
#include "pipa_secure_session.h"

namespace pipa {

// Client side of the v2 handshake. This class remains separate from
// PipaProtocol v1 so the encrypted transport can be enabled atomically after
// the handshake has passed on a real board.
class PipaSecureHandshake {
 public:
  static constexpr size_t kKeyBytes = 32;
  static constexpr size_t kNonceBytes = 32;
  static constexpr size_t kSignatureBytes = 64;

  PipaSecureHandshake() = default;
  ~PipaSecureHandshake() { clear(); }

  bool beginClient(DeviceIdentity& identity, const char* client_id, const char* session_id = nullptr);
  bool started() const { return started_; }
  bool complete() const { return complete_; }
  const String& sessionId() const { return session_id_; }

  // The returned JSON is the v2 ClientHello wire message. It contains no
  // private key material; the ephemeral private scalar remains in RAM.
  String clientHelloJson() const;

  // Verify the pinned server Ed25519 identity, derive X25519 shared material,
  // and initialise the supplied record layer. server_public_key is raw 32
  // byte Ed25519 data obtained from pairing metadata, never from the channel.
  bool acceptServerHello(
      JsonObjectConst server_hello,
      const uint8_t server_public_key[kKeyBytes],
      PipaSecureSession& session,
      const char* expected_server_id = nullptr);

  void clear();

 private:
  static bool validIdentifier(const char* value);
  static bool decodeBase64Url(const char* value, uint8_t* output, size_t output_length);
  static String encodeBase64Url(const uint8_t* bytes, size_t length);
  static String clientUnsignedJson(
      const String& session_id,
      const String& client_id,
      const String& client_ephemeral_public_key,
      const String& client_nonce);
  static String clientSignedJson(
      const String& session_id,
      const String& client_id,
      const String& client_ephemeral_public_key,
      const String& client_nonce);
  static String transcriptJson(
      const String& session_id,
      const String& client_id,
      const String& client_ephemeral_public_key,
      const String& client_nonce,
      const String& server_id,
      const String& server_ephemeral_public_key,
      const String& server_nonce);
  static String serverSignedJson(
      const String& session_id,
      const String& client_id,
      const String& client_ephemeral_public_key,
      const String& client_nonce,
      const String& server_id,
      const String& server_ephemeral_public_key,
      const String& server_nonce);

  DeviceIdentity* identity_ = nullptr;
  String session_id_;
  String client_id_;
  String client_ephemeral_public_key_;
  String client_nonce_;
  uint8_t client_ephemeral_private_key_[kKeyBytes] = {};
  bool started_ = false;
  bool complete_ = false;
};

}  // namespace pipa
