#include "pipa_secure_handshake.h"

#include <Curve25519.h>
#include <Crypto.h>
#include <Ed25519.h>
#include <SHA256.h>
#include <esp_system.h>

#include <string.h>

namespace pipa {
namespace {

constexpr char kBase64UrlAlphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

int base64Value(char character) {
  if (character >= 'A' && character <= 'Z') return character - 'A';
  if (character >= 'a' && character <= 'z') return character - 'a' + 26;
  if (character >= '0' && character <= '9') return character - '0' + 52;
  if (character == '-') return 62;
  if (character == '_') return 63;
  return -1;
}

}  // namespace

bool PipaSecureHandshake::validIdentifier(const char* value) {
  if (value == nullptr || value[0] == '\0') return false;
  size_t length = 0;
  while (value[length] != '\0') {
    if (++length > 128) return false;
    const char character = value[length - 1];
    if (!((character >= 'a' && character <= 'z') ||
          (character >= 'A' && character <= 'Z') ||
          (character >= '0' && character <= '9') || character == '-' || character == '_')) {
      return false;
    }
  }
  return true;
}

bool PipaSecureHandshake::hasExactServerHelloFields(JsonObjectConst object) {
  size_t field_count = 0;
  for (JsonPairConst pair : object) {
    const char* key = pair.key().c_str();
    if (strcmp(key, "client_ephemeral_public_key") != 0 &&
        strcmp(key, "client_id") != 0 && strcmp(key, "client_nonce") != 0 &&
        strcmp(key, "protocol_version") != 0 && strcmp(key, "server_ephemeral_public_key") != 0 &&
        strcmp(key, "server_id") != 0 && strcmp(key, "server_nonce") != 0 &&
        strcmp(key, "session_id") != 0 && strcmp(key, "signature") != 0) {
      return false;
    }
    ++field_count;
  }
  return field_count == 9;
}

String PipaSecureHandshake::encodeBase64Url(const uint8_t* bytes, size_t length) {
  if (bytes == nullptr && length != 0) return String();
  String value;
  value.reserve(((length + 2) / 3) * 4);
  for (size_t index = 0; index < length; index += 3) {
    const uint32_t block = static_cast<uint32_t>(bytes[index]) << 16 |
                           static_cast<uint32_t>(index + 1 < length ? bytes[index + 1] : 0) << 8 |
                           static_cast<uint32_t>(index + 2 < length ? bytes[index + 2] : 0);
    value += kBase64UrlAlphabet[(block >> 18) & 0x3F];
    value += kBase64UrlAlphabet[(block >> 12) & 0x3F];
    if (index + 1 < length) value += kBase64UrlAlphabet[(block >> 6) & 0x3F];
    if (index + 2 < length) value += kBase64UrlAlphabet[block & 0x3F];
  }
  return value;
}

bool PipaSecureHandshake::decodeBase64Url(
    const char* value,
    uint8_t* output,
    size_t output_length) {
  if (value == nullptr || output == nullptr) return false;
  const size_t input_length = strlen(value);
  // The caller always knows the exact decoded size. Enforcing the canonical
  // unpadded length prevents oversized inputs and non-canonical padding bits
  // from being accepted as a second encoding of the same key/signature.
  const size_t expected_input_length = (output_length * 8 + 5) / 6;
  if (input_length == 0 || input_length != expected_input_length || input_length % 4 == 1) {
    return false;
  }
  size_t output_index = 0;
  uint32_t accumulator = 0;
  uint8_t bits = 0;
  for (size_t index = 0; index < input_length; ++index) {
    const int digit = base64Value(value[index]);
    if (digit < 0) return false;
    accumulator = (accumulator << 6) | static_cast<uint32_t>(digit);
    bits = static_cast<uint8_t>(bits + 6);
    if (bits >= 8) {
      bits = static_cast<uint8_t>(bits - 8);
      if (output_index >= output_length) return false;
      output[output_index++] = static_cast<uint8_t>((accumulator >> bits) & 0xFF);
      if (bits == 0) {
        accumulator = 0;
      } else {
        accumulator &= (static_cast<uint32_t>(1) << bits) - 1;
      }
    }
  }
  return output_index == output_length && bits < 6 &&
         encodeBase64Url(output, output_length) == String(value);
}

String PipaSecureHandshake::clientUnsignedJson(
    const String& session_id,
    const String& client_id,
    const String& client_ephemeral_public_key,
    const String& client_nonce) {
  return String("{\"client_ephemeral_public_key\":\"") + client_ephemeral_public_key +
         "\",\"client_id\":\"" + client_id + "\",\"client_nonce\":\"" + client_nonce +
         "\",\"protocol_version\":2,\"session_id\":\"" + session_id + "\"}";
}

String PipaSecureHandshake::clientSignedJson(
    const String& session_id,
    const String& client_id,
    const String& client_ephemeral_public_key,
    const String& client_nonce) {
  return String("{\"client_ephemeral_public_key\":\"") + client_ephemeral_public_key +
         "\",\"client_id\":\"" + client_id + "\",\"client_nonce\":\"" + client_nonce +
         "\",\"protocol_version\":2,\"role\":\"client\",\"session_id\":\"" + session_id +
         "\"}";
}

String PipaSecureHandshake::transcriptJson(
    const String& session_id,
    const String& client_id,
    const String& client_ephemeral_public_key,
    const String& client_nonce,
    const String& server_id,
    const String& server_ephemeral_public_key,
    const String& server_nonce) {
  return String("{\"client_ephemeral_public_key\":\"") + client_ephemeral_public_key +
         "\",\"client_id\":\"" + client_id + "\",\"client_nonce\":\"" + client_nonce +
         "\",\"protocol_version\":2,\"server_ephemeral_public_key\":\"" +
         server_ephemeral_public_key + "\",\"server_id\":\"" + server_id +
         "\",\"server_nonce\":\"" + server_nonce + "\",\"session_id\":\"" + session_id + "\"}";
}

String PipaSecureHandshake::serverSignedJson(
    const String& session_id,
    const String& client_id,
    const String& client_ephemeral_public_key,
    const String& client_nonce,
    const String& server_id,
    const String& server_ephemeral_public_key,
    const String& server_nonce) {
  return String("{\"client_ephemeral_public_key\":\"") + client_ephemeral_public_key +
         "\",\"client_id\":\"" + client_id + "\",\"client_nonce\":\"" + client_nonce +
         "\",\"protocol_version\":2,\"role\":\"server\",\"server_ephemeral_public_key\":\"" +
         server_ephemeral_public_key + "\",\"server_id\":\"" + server_id +
         "\",\"server_nonce\":\"" + server_nonce + "\",\"session_id\":\"" + session_id + "\"}";
}

bool PipaSecureHandshake::beginClient(
    DeviceIdentity& identity,
    const char* client_id,
    const char* session_id) {
  clear();
  if (!identity.ready() || !validIdentifier(client_id)) return false;
  identity_ = &identity;
  client_id_ = client_id;

  uint8_t session_bytes[16] = {};
  if (session_id == nullptr) {
    esp_fill_random(session_bytes, sizeof(session_bytes));
    session_id_ = encodeBase64Url(session_bytes, sizeof(session_bytes));
  } else if (!validIdentifier(session_id)) {
    clear();
    return false;
  } else {
    session_id_ = session_id;
  }

  esp_fill_random(client_ephemeral_private_key_, sizeof(client_ephemeral_private_key_));
  client_ephemeral_private_key_[0] &= 0xF8;
  client_ephemeral_private_key_[31] = (client_ephemeral_private_key_[31] & 0x7F) | 0x40;
  uint8_t public_key[kKeyBytes] = {};
  if (!Curve25519::eval(public_key, client_ephemeral_private_key_, nullptr)) {
    clear();
    return false;
  }
  client_ephemeral_public_key_ = encodeBase64Url(public_key, sizeof(public_key));

  uint8_t nonce[kNonceBytes] = {};
  esp_fill_random(nonce, sizeof(nonce));
  client_nonce_ = encodeBase64Url(nonce, sizeof(nonce));
  clean(public_key, sizeof(public_key));
  clean(nonce, sizeof(nonce));
  started_ = !client_ephemeral_public_key_.isEmpty() && !client_nonce_.isEmpty();
  return started_;
}

String PipaSecureHandshake::clientHelloJson() const {
  if (!started_ || identity_ == nullptr) return String();
  const String unsigned_json = clientUnsignedJson(
      session_id_, client_id_, client_ephemeral_public_key_, client_nonce_);
  const String signature = identity_->signBase64Url(clientSignedJson(
      session_id_, client_id_, client_ephemeral_public_key_, client_nonce_));
  if (signature.isEmpty()) return String();
  return unsigned_json.substring(0, unsigned_json.length() - 1) +
         ",\"signature\":\"" + signature + "\"}";
}

bool PipaSecureHandshake::acceptServerHello(
    JsonObjectConst server_hello,
    const uint8_t server_public_key[kKeyBytes],
    PipaSecureSession& session,
    const char* expected_server_id) {
  if (!started_ || complete_ || server_hello.isNull() || server_public_key == nullptr ||
      !hasExactServerHelloFields(server_hello) ||
      !server_hello["protocol_version"].is<int>() ||
      !server_hello["client_ephemeral_public_key"].is<const char*>() ||
      !server_hello["client_id"].is<const char*>() ||
      !server_hello["client_nonce"].is<const char*>() ||
      !server_hello["server_ephemeral_public_key"].is<const char*>() ||
      !server_hello["server_id"].is<const char*>() ||
      !server_hello["server_nonce"].is<const char*>() ||
      !server_hello["session_id"].is<const char*>() ||
      !server_hello["signature"].is<const char*>() ||
      (server_hello["protocol_version"] | 0) != 2) {
    return false;
  }

  const char* response_session_id = server_hello["session_id"] | "";
  const char* response_client_id = server_hello["client_id"] | "";
  const char* response_client_ephemeral_public_key = server_hello["client_ephemeral_public_key"] | "";
  const char* response_client_nonce = server_hello["client_nonce"] | "";
  const char* server_id = server_hello["server_id"] | "";
  const char* server_ephemeral_public_key = server_hello["server_ephemeral_public_key"] | "";
  const char* server_nonce = server_hello["server_nonce"] | "";
  const char* signature = server_hello["signature"] | "";
  if (!validIdentifier(response_session_id) || !validIdentifier(server_id) ||
      (expected_server_id != nullptr &&
       (!validIdentifier(expected_server_id) || strcmp(server_id, expected_server_id) != 0)) ||
      strcmp(response_session_id, session_id_.c_str()) != 0 ||
      strcmp(response_client_id, client_id_.c_str()) != 0 ||
      strcmp(response_client_ephemeral_public_key, client_ephemeral_public_key_.c_str()) != 0 ||
      strcmp(response_client_nonce, client_nonce_.c_str()) != 0 ||
      strlen(server_ephemeral_public_key) == 0 || strlen(server_nonce) == 0 ||
      strlen(signature) == 0) {
    return false;
  }

  uint8_t server_ephemeral_key[kKeyBytes] = {};
  uint8_t server_nonce_bytes[kNonceBytes] = {};
  uint8_t server_signature[kSignatureBytes] = {};
  if (!decodeBase64Url(server_ephemeral_public_key, server_ephemeral_key, sizeof(server_ephemeral_key)) ||
      !decodeBase64Url(server_nonce, server_nonce_bytes, sizeof(server_nonce_bytes)) ||
      !decodeBase64Url(signature, server_signature, sizeof(server_signature))) {
    return false;
  }

  const String transcript = transcriptJson(
      session_id_,
      client_id_,
      client_ephemeral_public_key_,
      client_nonce_,
      server_id,
      server_ephemeral_public_key,
      server_nonce);
  const String signed_transcript = serverSignedJson(
      session_id_,
      client_id_,
      client_ephemeral_public_key_,
      client_nonce_,
      server_id,
      server_ephemeral_public_key,
      server_nonce);
  if (!Ed25519::verify(
          server_signature,
          server_public_key,
          signed_transcript.c_str(),
          signed_transcript.length())) {
    return false;
  }

  uint8_t shared_secret[kKeyBytes] = {};
  if (!Curve25519::eval(shared_secret, client_ephemeral_private_key_, server_ephemeral_key)) {
    clean(shared_secret, sizeof(shared_secret));
    return false;
  }
  uint8_t transcript_hash[kNonceBytes] = {};
  SHA256 hash;
  hash.update(transcript.c_str(), transcript.length());
  hash.finalize(transcript_hash, sizeof(transcript_hash));
  if (!session.beginFromSharedSecret(
          session_id_.c_str(), shared_secret, transcript_hash, true)) {
    clean(shared_secret, sizeof(shared_secret));
    clean(transcript_hash, sizeof(transcript_hash));
    return false;
  }

  clean(shared_secret, sizeof(shared_secret));
  clean(transcript_hash, sizeof(transcript_hash));
  clean(server_ephemeral_key, sizeof(server_ephemeral_key));
  clean(server_nonce_bytes, sizeof(server_nonce_bytes));
  clean(server_signature, sizeof(server_signature));
  clean(client_ephemeral_private_key_, sizeof(client_ephemeral_private_key_));
  complete_ = true;
  return true;
}

void PipaSecureHandshake::clear() {
  identity_ = nullptr;
  session_id_.clear();
  client_id_.clear();
  client_ephemeral_public_key_.clear();
  client_nonce_.clear();
  clean(client_ephemeral_private_key_, sizeof(client_ephemeral_private_key_));
  started_ = false;
  complete_ = false;
}

}  // namespace pipa
