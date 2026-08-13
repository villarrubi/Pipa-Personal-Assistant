#pragma once

#include <Arduino.h>

#include <ChaChaPoly.h>

#include <stddef.h>
#include <stdint.h>

namespace pipa {

// Record-layer counterpart of windows-agent/secure_session.py.  It is
// intentionally not wired into PipaProtocol v1 yet: the v2 handshake must be
// validated with cross-language vectors before any payload is encrypted on a
// real device.
class PipaSecureSession {
 public:
  static constexpr size_t kKeyBytes = 32;
  static constexpr size_t kTranscriptHashBytes = 32;
  static constexpr size_t kNoncePrefixBytes = 4;
  static constexpr size_t kNonceBytes = 12;
  static constexpr size_t kTagBytes = 16;
  static constexpr size_t kMaxRecordBytes = 64 * 1024;
  static constexpr size_t kMaxAdditionalDataBytes = 1024;
  static constexpr uint64_t kMaxSequence = UINT64_MAX;

  PipaSecureSession() = default;
  ~PipaSecureSession() { clear(); }

  // Derive directional keys from the X25519 shared secret and the SHA-256
  // transcript hash.  The ordering matches Python's HKDF output exactly:
  // client key, server key, client nonce prefix, server nonce prefix.
  bool beginFromSharedSecret(
      const char* session_id,
      const uint8_t shared_secret[kKeyBytes],
      const uint8_t transcript_hash[kTranscriptHashBytes],
      bool client_role);

  bool ready() const { return ready_; }
  const String& sessionId() const { return session_id_; }
  uint64_t nextSendSequence() const { return send_sequence_; }
  uint64_t nextReceiveSequence() const { return receive_sequence_; }

  // Deterministic cross-language vector used only by the dedicated
  // secure-session-vector PlatformIO environment. It has no production side
  // effects and uses public test constants, never a device identity.
  static bool vectorSelfTest();

  // The output is ciphertext followed by a 16-byte Poly1305 tag.  The
  // protocol header is authenticated internally and additional_data is
  // authenticated after it, matching Python's header + AAD construction.
  bool seal(
      const uint8_t* plaintext,
      size_t plaintext_length,
      const uint8_t* additional_data,
      size_t additional_data_length,
      uint8_t* output,
      size_t output_capacity,
      size_t* output_length);

  // sequence must equal the next expected inbound sequence.  The receive
  // counter advances only after the Poly1305 tag verifies.
  bool open(
      uint64_t sequence,
      const uint8_t* ciphertext_and_tag,
      size_t ciphertext_and_tag_length,
      const uint8_t* additional_data,
      size_t additional_data_length,
      uint8_t* output,
      size_t output_capacity,
      size_t* output_length);

  void clear();

 private:
  static bool validSessionId(const char* session_id);
  static String headerFor(const String& session_id, uint64_t sequence);
  static void buildNonce(uint8_t nonce[kNonceBytes], const uint8_t prefix[kNoncePrefixBytes], uint64_t sequence);
  static void addAuthenticatedData(
      ::ChaChaPoly& cipher,
      const String& header,
      const uint8_t* additional_data,
      size_t additional_data_length);

  String session_id_;
  uint8_t send_key_[kKeyBytes] = {};
  uint8_t receive_key_[kKeyBytes] = {};
  uint8_t send_nonce_prefix_[kNoncePrefixBytes] = {};
  uint8_t receive_nonce_prefix_[kNoncePrefixBytes] = {};
  uint64_t send_sequence_ = 0;
  uint64_t receive_sequence_ = 0;
  bool ready_ = false;
};

}  // namespace pipa
