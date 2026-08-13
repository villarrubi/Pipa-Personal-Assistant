#include "pipa_secure_session.h"

#include <ChaChaPoly.h>
#include <Crypto.h>
#include <HKDF.h>
#include <SHA256.h>

#include <string.h>

namespace pipa {
namespace {

constexpr uint8_t kClientKeyOffset = 0;
constexpr uint8_t kServerKeyOffset = 32;
constexpr uint8_t kClientNoncePrefixOffset = 64;
constexpr uint8_t kServerNoncePrefixOffset = 68;
constexpr size_t kDerivedBytes = 72;
constexpr char kHkdfInfo[] = "pipa/secure-session/v2";

bool validBuffer(const uint8_t* value, size_t length) {
  return length == 0 || value != nullptr;
}

}  // namespace

bool PipaSecureSession::validSessionId(const char* session_id) {
  if (session_id == nullptr || session_id[0] == '\0') return false;
  size_t length = 0;
  while (session_id[length] != '\0') {
    if (++length > 128) return false;
    const char character = session_id[length - 1];
    if (!((character >= 'a' && character <= 'z') ||
          (character >= 'A' && character <= 'Z') ||
          (character >= '0' && character <= '9') || character == '-' || character == '_')) {
      return false;
    }
  }
  return true;
}

String PipaSecureSession::headerFor(const String& session_id, uint64_t sequence) {
  // This is the sorted-key, compact JSON equivalent of Python's canonical
  // header: protocol_version, sequence, session_id.
  String header;
  header.reserve(64 + session_id.length());
  header += "{\"protocol_version\":2,\"sequence\":";
  header += String(static_cast<unsigned long long>(sequence));
  header += ",\"session_id\":\"";
  header += session_id;
  header += "\"}";
  return header;
}

void PipaSecureSession::buildNonce(
    uint8_t nonce[kNonceBytes],
    const uint8_t prefix[kNoncePrefixBytes],
    uint64_t sequence) {
  memcpy(nonce, prefix, kNoncePrefixBytes);
  for (size_t index = 0; index < sizeof(sequence); ++index) {
    nonce[kNonceBytes - 1 - index] = static_cast<uint8_t>(sequence >> (index * 8));
  }
}

void PipaSecureSession::addAuthenticatedData(
    ChaChaPoly& cipher,
    const String& header,
    const uint8_t* additional_data,
    size_t additional_data_length) {
  cipher.addAuthData(header.c_str(), header.length());
  if (additional_data_length > 0) cipher.addAuthData(additional_data, additional_data_length);
}

bool PipaSecureSession::beginFromSharedSecret(
    const char* session_id,
    const uint8_t shared_secret[kKeyBytes],
    const uint8_t transcript_hash[kTranscriptHashBytes],
    bool client_role) {
  if (!validSessionId(session_id) || shared_secret == nullptr || transcript_hash == nullptr) return false;

  bool shared_secret_is_zero = true;
  for (size_t index = 0; index < kKeyBytes; ++index) {
    shared_secret_is_zero = shared_secret_is_zero && shared_secret[index] == 0;
  }
  if (shared_secret_is_zero) return false;

  uint8_t info[sizeof(kHkdfInfo) - 1 + kTranscriptHashBytes] = {};
  memcpy(info, kHkdfInfo, sizeof(kHkdfInfo) - 1);
  memcpy(info + sizeof(kHkdfInfo) - 1, transcript_hash, kTranscriptHashBytes);

  uint8_t derived[kDerivedBytes] = {};
  hkdf<SHA256>(
      derived,
      sizeof(derived),
      shared_secret,
      kKeyBytes,
      transcript_hash,
      kTranscriptHashBytes,
      info,
      sizeof(info));

  session_id_ = session_id;
  const uint8_t* local_key = client_role ? derived + kClientKeyOffset : derived + kServerKeyOffset;
  const uint8_t* remote_key = client_role ? derived + kServerKeyOffset : derived + kClientKeyOffset;
  const uint8_t* local_prefix =
      client_role ? derived + kClientNoncePrefixOffset : derived + kServerNoncePrefixOffset;
  const uint8_t* remote_prefix =
      client_role ? derived + kServerNoncePrefixOffset : derived + kClientNoncePrefixOffset;
  memcpy(send_key_, local_key, kKeyBytes);
  memcpy(receive_key_, remote_key, kKeyBytes);
  memcpy(send_nonce_prefix_, local_prefix, kNoncePrefixBytes);
  memcpy(receive_nonce_prefix_, remote_prefix, kNoncePrefixBytes);
  send_sequence_ = 0;
  receive_sequence_ = 0;
  ready_ = true;
  clean(derived, sizeof(derived));
  clean(info, sizeof(info));
  return true;
}

bool PipaSecureSession::seal(
    const uint8_t* plaintext,
    size_t plaintext_length,
    const uint8_t* additional_data,
    size_t additional_data_length,
    uint8_t* output,
    size_t output_capacity,
    size_t* output_length) {
  if (output_length != nullptr) *output_length = 0;
  if (!ready_ || !validBuffer(plaintext, plaintext_length) ||
      !validBuffer(additional_data, additional_data_length) || output == nullptr ||
      output_length == nullptr || plaintext_length > kMaxRecordBytes ||
      additional_data_length > kMaxAdditionalDataBytes ||
      output_capacity < plaintext_length + kTagBytes || send_sequence_ == kMaxSequence) {
    return false;
  }

  ChaChaPoly cipher;
  uint8_t nonce[kNonceBytes] = {};
  buildNonce(nonce, send_nonce_prefix_, send_sequence_);
  const String header = headerFor(session_id_, send_sequence_);
  if (!cipher.setKey(send_key_, sizeof(send_key_)) || !cipher.setIV(nonce, sizeof(nonce))) return false;
  addAuthenticatedData(cipher, header, additional_data, additional_data_length);
  cipher.encrypt(output, plaintext, plaintext_length);
  cipher.computeTag(output + plaintext_length, kTagBytes);
  *output_length = plaintext_length + kTagBytes;
  ++send_sequence_;
  cipher.clear();
  clean(nonce, sizeof(nonce));
  return true;
}

bool PipaSecureSession::open(
    uint64_t sequence,
    const uint8_t* ciphertext_and_tag,
    size_t ciphertext_and_tag_length,
    const uint8_t* additional_data,
    size_t additional_data_length,
    uint8_t* output,
    size_t output_capacity,
    size_t* output_length) {
  if (output_length != nullptr) *output_length = 0;
  if (!ready_ || ciphertext_and_tag == nullptr || ciphertext_and_tag_length < kTagBytes ||
      ciphertext_and_tag_length > kMaxRecordBytes + kTagBytes ||
      !validBuffer(additional_data, additional_data_length) || output == nullptr ||
      output_length == nullptr || additional_data_length > kMaxAdditionalDataBytes ||
      output_capacity < ciphertext_and_tag_length - kTagBytes || sequence != receive_sequence_ ||
      sequence == kMaxSequence) {
    return false;
  }

  const size_t plaintext_length = ciphertext_and_tag_length - kTagBytes;
  ChaChaPoly cipher;
  uint8_t nonce[kNonceBytes] = {};
  buildNonce(nonce, receive_nonce_prefix_, sequence);
  const String header = headerFor(session_id_, sequence);
  if (!cipher.setKey(receive_key_, sizeof(receive_key_)) || !cipher.setIV(nonce, sizeof(nonce))) return false;
  addAuthenticatedData(cipher, header, additional_data, additional_data_length);
  cipher.decrypt(output, ciphertext_and_tag, plaintext_length);
  if (!cipher.checkTag(ciphertext_and_tag + plaintext_length, kTagBytes)) {
    memset(output, 0, plaintext_length);
    cipher.clear();
    clean(nonce, sizeof(nonce));
    return false;
  }
  *output_length = plaintext_length;
  ++receive_sequence_;
  cipher.clear();
  clean(nonce, sizeof(nonce));
  return true;
}

void PipaSecureSession::clear() {
  session_id_.clear();
  clean(send_key_, sizeof(send_key_));
  clean(receive_key_, sizeof(receive_key_));
  clean(send_nonce_prefix_, sizeof(send_nonce_prefix_));
  clean(receive_nonce_prefix_, sizeof(receive_nonce_prefix_));
  send_sequence_ = 0;
  receive_sequence_ = 0;
  ready_ = false;
}

bool PipaSecureSession::vectorSelfTest() {
  static constexpr uint8_t shared_secret[kKeyBytes] = {
      0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
      0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10,
      0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18,
      0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20};
  static constexpr uint8_t transcript_hash[kTranscriptHashBytes] = {
      0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
      0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F,
      0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37,
      0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F};
  static constexpr uint8_t expected_ciphertext_and_tag[] = {
      0xA0, 0x37, 0x84, 0x0F, 0x89, 0xC1, 0x1C, 0x34,
      0x8E, 0x8F, 0xDC, 0xC7, 0xFA, 0x5A, 0x12, 0x77,
      0x09, 0xB2, 0xB4, 0x5A, 0x0A, 0xA2, 0xDF, 0xBC,
      0x60, 0xA3, 0x51, 0x56, 0x08, 0x6E};
  static constexpr uint8_t plaintext[] = {
      'v', 'e', 'c', 't', 'o', 'r', ' ', 'p', 'a', 'y', 'l', 'o', 'a', 'd'};
  static constexpr uint8_t additional_data[] = {'r', 'o', 'u', 't', 'e', ':', 'u', 's', 'b'};

  uint8_t zero_secret[kKeyBytes] = {};
  PipaSecureSession invalid;
  if (invalid.beginFromSharedSecret("vector-session", zero_secret, transcript_hash, true)) {
    return false;
  }

  PipaSecureSession client;
  PipaSecureSession server;
  if (!client.beginFromSharedSecret("vector-session", shared_secret, transcript_hash, true) ||
      !server.beginFromSharedSecret("vector-session", shared_secret, transcript_hash, false)) {
    return false;
  }

  uint8_t sealed[sizeof(expected_ciphertext_and_tag)] = {};
  size_t sealed_length = 0;
  if (!client.seal(
          plaintext,
          sizeof(plaintext),
          additional_data,
          sizeof(additional_data),
          sealed,
          sizeof(sealed),
          &sealed_length) ||
      sealed_length != sizeof(expected_ciphertext_and_tag) ||
      memcmp(sealed, expected_ciphertext_and_tag, sizeof(expected_ciphertext_and_tag)) != 0) {
    return false;
  }

  uint8_t opened[sizeof(plaintext)] = {};
  size_t opened_length = 0;
  if (!server.open(
          0,
          sealed,
          sealed_length,
          additional_data,
          sizeof(additional_data),
          opened,
          sizeof(opened),
          &opened_length) ||
      opened_length != sizeof(plaintext) ||
      memcmp(opened, plaintext, sizeof(plaintext)) != 0) {
    return false;
  }

  return true;
}

}  // namespace pipa
