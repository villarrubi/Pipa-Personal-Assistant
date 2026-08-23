#include "pipa_secure_protocol.h"

#include "pipa_text_policy.h"
#include "pipa_json_policy.h"

#include <memory>
#include <new>
#include <string.h>

#include <WiFi.h>

#include "Crypto.h"

namespace pipa {
namespace {

constexpr char kBase64UrlAlphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
constexpr uint8_t kJsonAad[] = "pipa/json/v2";

bool isSessionResetHint(JsonObjectConst object) {
  return object.size() == 2 && object["protocol_version"].is<int>() &&
         (object["protocol_version"] | 0) == 2 && object["type"].is<const char*>() &&
         strcmp(object["type"] | "", "session_reset") == 0;
}

int base64Value(char character) {
  if (character >= 'A' && character <= 'Z') return character - 'A';
  if (character >= 'a' && character <= 'z') return character - 'a' + 26;
  if (character >= '0' && character <= '9') return character - '0' + 52;
  if (character == '-') return 62;
  if (character == '_') return 63;
  return -1;
}

}  // namespace

PipaSecureProtocol::PipaSecureProtocol(
    Stream& transport,
    DeviceIdentity& identity,
    const char* device_id,
    const char* firmware_version,
    const char* server_id,
    const char* server_public_key)
    : transport_(transport),
      identity_(identity),
      device_id_(device_id),
      firmware_version_(firmware_version),
      server_id_(server_id),
      server_public_key_(server_public_key) {
  inbound_line_.reserve(1024);
}

void PipaSecureProtocol::begin() {
  resetHandshake();
  sendHandshake();
}

void PipaSecureProtocol::setHardwareCapabilities(
    bool display_ready,
    bool touch_ready,
    bool audio_probe_ready) {
  display_ready_ = display_ready;
  touch_ready_ = touch_ready;
  audio_probe_ready_ = audio_probe_ready;
}

void PipaSecureProtocol::setAudioState(PipaAudioState state) {
  if (audio_state_ == state) return;
  audio_state_ = state;
  if (authenticated_) {
    last_status_ = millis();
    sendDeviceStatus();
  }
}

void PipaSecureProtocol::setBatteryPercent(int battery_percent) {
  battery_percent_ = battery_percent >= 0 && battery_percent <= 100 ? battery_percent : -1;
}

void PipaSecureProtocol::poll() {
  readTransport();
  const uint32_t now = millis();
  if (authenticated_ && now - last_server_message_ >= kServerTimeoutMs) {
    log("secure server heartbeat timed out; restarting handshake");
    resetHandshake();
    last_handshake_ = now;
    sendHandshake();
    return;
  }
  if (!authenticated_ && now - last_handshake_ >= kHandshakeRetryMs) {
    last_handshake_ = now;
    sendHandshake();
  }
  if (authenticated_ && now - last_heartbeat_ >= kHeartbeatMs) {
    last_heartbeat_ = now;
    sendHeartbeat();
  }
  if (authenticated_ && now - last_status_ >= kStatusMs) {
    last_status_ = now;
    sendDeviceStatus();
  }
}

void PipaSecureProtocol::maintainUi(uint32_t now_ms) {
  if (ui_.state != "idle" || ui_.caption.isEmpty()) {
    transient_idle_started_at_ = 0;
    return;
  }
  if (transient_idle_started_at_ == 0) {
    transient_idle_started_at_ = now_ms;
    return;
  }
  if (now_ms - transient_idle_started_at_ >= kTransientIdleCaptionMs) {
    ui_.caption.clear();
    transient_idle_started_at_ = 0;
  }
}

void PipaSecureProtocol::sendGesture(const char* gesture) {
  if (!authenticated_ || !isSafeGesture(gesture)) return;
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "gesture";
  document["gesture"] = gesture;
  sendEncrypted(document);
}

void PipaSecureProtocol::sendTextInput(const char* text, const char* source) {
  const char* safe_source = source == nullptr || source[0] == '\0' ? "unknown" : source;
  if (!authenticated_ || !isSafeDisplayText(text, 4000) || !isSafeTextSource(safe_source)) return;
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "text_input";
  document["text"] = text;
  document["source"] = safe_source;
  sendEncrypted(document);
}

void PipaSecureProtocol::sendConfirmation(bool accepted) {
  if (!authenticated_ || ui_.confirmation_id.isEmpty() || ui_.confirmation_summary.isEmpty()) return;
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "confirm";
  document["confirmation_id"] = ui_.confirmation_id;
  document["accepted"] = accepted;
  sendEncrypted(document);
}

#if PIPA_AUDIO_CAPTURE_ENABLED
bool PipaSecureProtocol::sendHoldStart() {
  if (!authenticated_ || audio_state_ != PipaAudioState::kCodecReady) return false;
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "hold_start";
  sendEncrypted(document);
  return true;
}

bool PipaSecureProtocol::beginAudioStream(const char* stream_id) {
  if (!authenticated_ || audio_sender_ != nullptr || audio_state_ != PipaAudioState::kListening ||
      !PipaSecureAudio::validStreamId(stream_id)) {
    return false;
  }
  audio_sender_ = new (std::nothrow) PipaSecureAudioSender(session_, stream_id);
  if (audio_sender_ == nullptr || !audio_sender_->valid()) {
    delete audio_sender_;
    audio_sender_ = nullptr;
    return false;
  }
  return true;
}

bool PipaSecureProtocol::sendAudioChunk(
    const uint8_t* samples,
    size_t samples_length,
    bool final) {
  if (!authenticated_ || audio_sender_ == nullptr) return false;
  static PipaSecureAudioFrame frame;
  if (!audio_sender_->sealChunk(samples, samples_length, final, frame)) {
    cancelAudioStream();
    return false;
  }

  JsonDocument document;
  document["audio_protocol_version"] = frame.audio_protocol_version;
  document["bits_per_sample"] = frame.bits_per_sample;
  document["channels"] = frame.channels;
  document["chunk_index"] = frame.chunk_index;
  document["ciphertext"] = encodeBase64Url(frame.ciphertext, frame.ciphertext_length);
  document["final"] = frame.final;
  document["protocol_version"] = 2;
  document["sample_rate"] = frame.sample_rate;
  document["sequence"] = frame.sequence;
  document["session_id"] = session_.sessionId();
  document["stream_id"] = frame.stream_id;
  sendJson(document);
  clean(frame.ciphertext, sizeof(frame.ciphertext));
  frame.ciphertext_length = 0;

  if (final) {
    delete audio_sender_;
    audio_sender_ = nullptr;
  }
  return true;
}

void PipaSecureProtocol::cancelAudioStream() {
  if (audio_sender_ != nullptr) {
    audio_sender_->cancel();
    delete audio_sender_;
    audio_sender_ = nullptr;
  }
}

void PipaSecureProtocol::abortAudioStream() {
  cancelAudioStream();
  if (!authenticated_) return;
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "abort";
  sendEncrypted(document);
}
#endif

void PipaSecureProtocol::readTransport() {
  while (transport_.available()) {
    const char character = static_cast<char>(transport_.read());
    if (character == '\r') continue;
    if (character == '\n') {
      if (!dropping_oversized_line_ && !inbound_line_.isEmpty()) handleLine(inbound_line_);
      inbound_line_.clear();
      dropping_oversized_line_ = false;
      continue;
    }
    if (dropping_oversized_line_) continue;
    if (inbound_line_.length() >= kMaxInboundLine) {
      inbound_line_.clear();
      dropping_oversized_line_ = true;
      log("secure incoming message discarded: too large");
      continue;
    }
    inbound_line_ += character;
  }
}

void PipaSecureProtocol::handleLine(const String& line) {
  if (!isDuplicateFreeJson(line.c_str(), line.length())) {
    log("secure incoming message discarded: duplicate or invalid JSON");
    return;
  }
  JsonDocument document;
  if (deserializeJson(document, line) != DeserializationError::Ok) {
    log("secure incoming message discarded: invalid JSON");
    return;
  }
  JsonObjectConst object = document.as<JsonObjectConst>();
  if (object.isNull()) {
    log("secure incoming message discarded: not an object");
    return;
  }
  if (!authenticated_) {
    handleServerHello(object);
  } else {
    handleEncryptedFrame(object);
  }
}

void PipaSecureProtocol::handleServerHello(JsonObjectConst object) {
  if (handshake_.complete()) return;
  uint8_t server_public_key[kMaxKeyBytes] = {};
  if (!decodeServerKey(server_public_key) ||
      !handshake_.acceptServerHello(object, server_public_key, session_, server_id_)) {
    clean(server_public_key, sizeof(server_public_key));
    log("secure ServerHello rejected");
    return;
  }
  clean(server_public_key, sizeof(server_public_key));
  authenticated_ = true;
  last_server_message_ = millis();
  last_heartbeat_ = last_server_message_;
  last_status_ = last_server_message_;
  sendDeviceHello();
  sendDeviceStatus();
  log("secure session ready");
}

void PipaSecureProtocol::handleEncryptedFrame(JsonObjectConst object) {
  if (isSessionResetHint(object)) {
    // The desktop agent deliberately discards ephemeral keys on restart. A
    // reset hint can only tear down the current session; the replacement must
    // still complete the normal signed and allowlisted v2 handshake.
    resetHandshake();
    log("secure session restart requested");
    last_handshake_ = millis();
    sendHandshake();
    return;
  }
  if (!frameHasExactFields(object)) {
    rejectEncryptedFrame("invalid fields");
    return;
  }
  const uint64_t sequence = object["sequence"] | UINT64_MAX;
  const char* session_id = object["session_id"] | "";
  const char* ciphertext = object["ciphertext"] | "";
  if (!object["protocol_version"].is<int>() || !object["sequence"].is<uint64_t>() ||
      !object["session_id"].is<const char*>() || !object["ciphertext"].is<const char*>() ||
      (object["protocol_version"] | 0) != 2 || strcmp(session_id, session_.sessionId().c_str()) != 0 ||
      ciphertext[0] == '\0' || sequence != session_.nextReceiveSequence()) {
    rejectEncryptedFrame("header invalid");
    return;
  }
  std::unique_ptr<uint8_t[]> ciphertext_bytes(new (std::nothrow) uint8_t[kMaxCiphertext]());
  std::unique_ptr<uint8_t[]> plaintext(new (std::nothrow) uint8_t[kMaxPlaintext]());
  if (ciphertext_bytes == nullptr || plaintext == nullptr) {
    rejectEncryptedFrame("insufficient memory");
    return;
  }
  size_t decoded_length = 0;
  size_t plaintext_length = 0;
  if (!decodeBase64Url(ciphertext, ciphertext_bytes.get(), kMaxCiphertext, &decoded_length)) {
    clean(ciphertext_bytes.get(), kMaxCiphertext);
    clean(plaintext.get(), kMaxPlaintext);
    rejectEncryptedFrame("ciphertext invalid");
    return;
  }
  if (decoded_length < PipaSecureSession::kTagBytes ||
      !session_.open(
          sequence,
          ciphertext_bytes.get(),
          decoded_length,
          kJsonAad,
          sizeof(kJsonAad) - 1,
          plaintext.get(),
          kMaxPlaintext,
          &plaintext_length)) {
    clean(ciphertext_bytes.get(), kMaxCiphertext);
    clean(plaintext.get(), kMaxPlaintext);
    rejectEncryptedFrame("authentication failed");
    return;
  }
  if (!isDuplicateFreeJson(
          reinterpret_cast<const char*>(plaintext.get()), plaintext_length)) {
    clean(ciphertext_bytes.get(), kMaxCiphertext);
    clean(plaintext.get(), kMaxPlaintext);
    rejectEncryptedFrame("duplicate or invalid JSON");
    return;
  }
  JsonDocument document;
  if (deserializeJson(document, plaintext.get(), plaintext_length) != DeserializationError::Ok) {
    clean(ciphertext_bytes.get(), kMaxCiphertext);
    clean(plaintext.get(), kMaxPlaintext);
    rejectEncryptedFrame("invalid JSON");
    return;
  }
  last_server_message_ = millis();
  handleMessage(document.as<JsonObjectConst>());
  clean(ciphertext_bytes.get(), kMaxCiphertext);
  clean(plaintext.get(), kMaxPlaintext);
}

void PipaSecureProtocol::rejectEncryptedFrame(const char* reason) {
  // A failed authenticated record invalidates the whole session. Continuing
  // would leave the receive sequence/key state ambiguous and could turn a
  // corrupted transport into an indefinitely live authenticated channel.
  resetHandshake();
  last_handshake_ = millis();
  (void)reason;
  // Keep untrusted or implementation-specific rejection details out of the
  // serial channel. The transport is reset regardless of the reason.
  log("secure session reset");
}

void PipaSecureProtocol::handleMessage(JsonObjectConst object) {
  if ((object["protocol_version"] | 0) != 1) return;
  const char* type = object["type"] | "";
  if (strcmp(type, "ready") == 0) {
    updateUi(object["ui_state"].as<JsonObjectConst>());
  } else if (strcmp(type, "ui_state") == 0) {
    updateUi(object);
  } else if (strcmp(type, "confirm_request") == 0) {
    if (!ui_.confirmation_id.isEmpty()) return;
    const char* confirmation_id = object["confirmation_id"] | "";
    const char* summary = object["summary"] | "";
    if (!isSafeDisplayText(confirmation_id, 128) || !isSafeDisplayText(summary, 256)) return;
    ui_.confirmation_id = confirmation_id;
    ui_.confirmation_summary = summary;
    ui_.state = "confirm";
  } else if (strcmp(type, "device_hello_ack") == 0) {
    // The secure Core accepted the hardware capability announcement.
  } else if (strcmp(type, "tool_result") == 0) {
    ui_.confirmation_id.clear();
    ui_.confirmation_summary.clear();
  } else if (strcmp(type, "error") == 0) {
    const char* code = object["code"] | "unknown";
    if (strcmp(code, "authentication_failed") == 0 ||
        strcmp(code, "authentication_required") == 0 ||
        strcmp(code, "unknown_session") == 0) {
      resetHandshake();
      last_handshake_ = millis();
      log("secure authentication error; handshake restarted");
    } else {
      // Invalidate any stale physical confirmation and recover the display if
      // an error is not accompanied by a later ui_state frame. A subsequent
      // ui_state from Core still wins during this same poll cycle.
      ui_.state = "idle";
      ui_.caption = "La solicitud no ha podido completarse.";
      ui_.confirmation_id.clear();
      ui_.confirmation_summary.clear();
    }
  }
}

void PipaSecureProtocol::sendHandshake() {
  if (!identity_.ready() || !handshake_.beginClient(identity_, device_id_)) {
    log("secure handshake could not start");
    return;
  }
  // Repeat the public provisioning marker before every unauthenticated
  // handshake. USB CDC boot diagnostics can be emitted before Windows has
  // reopened the COM port after reset; this bounded, non-secret marker lets
  // an administrator recover the device fingerprint without exposing the
  // private identity or weakening the authenticated v2 handshake.
  log(String("PIPA_PUBLIC_KEY=") + identity_.publicKeyBase64Url());
  const String hello = handshake_.clientHelloJson();
  if (hello.isEmpty() || hello.length() + 1 > kMaxOutboundLine) {
    log("secure ClientHello could not be encoded");
    return;
  }
  transport_.print(hello);
  transport_.print('\n');
  last_handshake_ = millis();
}

void PipaSecureProtocol::sendHeartbeat() {
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "ping";
  document["request_id"] = String(millis(), HEX);
  sendEncrypted(document);
}

void PipaSecureProtocol::sendDeviceHello() {
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "device_hello";
  document["firmware_version"] = firmware_version_;
  JsonArray capabilities = document["capabilities"].to<JsonArray>();
  capabilities.add("usb_serial");
  if (touch_ready_) capabilities.add("touch");
  if (display_ready_) capabilities.add("display");
  if (audio_probe_ready_) capabilities.add("audio_probe");
#if PIPA_AUDIO_CAPTURE_ENABLED
  if (audio_state_ == PipaAudioState::kCodecReady) capabilities.add("audio_capture");
#endif
#if PIPA_ALWAYS_LISTENING_ENABLED
  if (local_wake_phrase_ready_) {
    capabilities.add("hands_free");
    capabilities.add("local_wake_phrase");
    capabilities.add("offline_wake_buffer");
  }
#endif
  capabilities.add("wol");
  capabilities.add("text_input");
  capabilities.add("device_status");
  sendEncrypted(document);
}

void PipaSecureProtocol::sendDeviceStatus() {
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "device_status";
  document["audio_state"] = pipaAudioStateName(audio_state_);
  if (battery_percent_ >= 0) document["battery_percent"] = battery_percent_;
  if (WiFi.status() == WL_CONNECTED) document["wifi_rssi"] = WiFi.RSSI();
  sendEncrypted(document);
}

void PipaSecureProtocol::sendJson(JsonDocument& document) {
  if (measureJson(document) + 1 > kMaxOutboundLine) {
    log("secure outgoing message discarded: too large");
    return;
  }
  serializeJson(document, transport_);
  transport_.print('\n');
}

void PipaSecureProtocol::sendEncrypted(JsonDocument& document) {
  if (!authenticated_) return;
  String plaintext;
  serializeJson(document, plaintext);
  if (plaintext.length() > kMaxPlaintext) {
    log("secure payload discarded: too large");
    return;
  }
  std::unique_ptr<uint8_t[]> ciphertext(new (std::nothrow) uint8_t[kMaxCiphertext]());
  if (ciphertext == nullptr) {
    log("secure payload encryption failed: insufficient memory");
    return;
  }
  size_t ciphertext_length = 0;
  const uint64_t sequence = session_.nextSendSequence();
  if (!session_.seal(
          reinterpret_cast<const uint8_t*>(plaintext.c_str()),
          plaintext.length(),
          kJsonAad,
          sizeof(kJsonAad) - 1,
          ciphertext.get(),
          kMaxCiphertext,
          &ciphertext_length)) {
    clean(ciphertext.get(), kMaxCiphertext);
    log("secure payload encryption failed");
    return;
  }
  JsonDocument frame;
  frame["ciphertext"] = encodeBase64Url(ciphertext.get(), ciphertext_length);
  frame["protocol_version"] = 2;
  frame["sequence"] = sequence;
  frame["session_id"] = session_.sessionId();
  sendJson(frame);
  clean(ciphertext.get(), kMaxCiphertext);
}

bool PipaSecureProtocol::decodeServerKey(uint8_t output[kMaxKeyBytes]) const {
  return decodeBase64Url(server_public_key_, output, kMaxKeyBytes);
}

bool PipaSecureProtocol::decodeBase64Url(
    const char* value,
    uint8_t* output,
    size_t output_capacity,
    size_t* decoded_length) {
  if (value == nullptr || output == nullptr) return false;
  const size_t input_length = strlen(value);
  if (input_length == 0 || input_length % 4 == 1) return false;
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
      if (output_index >= output_capacity) return false;
      output[output_index++] = static_cast<uint8_t>((accumulator >> bits) & 0xFF);
      accumulator = bits == 0 ? 0 : accumulator & ((static_cast<uint32_t>(1) << bits) - 1);
    }
  }
  if (bits >= 6 || (bits != 0 && accumulator != 0)) return false;
  if (decoded_length != nullptr) {
    *decoded_length = output_index;
    return true;
  }
  return output_index == output_capacity;
}

String PipaSecureProtocol::encodeBase64Url(const uint8_t* bytes, size_t length) {
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

bool PipaSecureProtocol::frameHasExactFields(JsonObjectConst object) {
  size_t fields = 0;
  for (JsonPairConst pair : object) {
    const char* key = pair.key().c_str();
    if (strcmp(key, "ciphertext") != 0 && strcmp(key, "protocol_version") != 0 &&
        strcmp(key, "sequence") != 0 && strcmp(key, "session_id") != 0) return false;
    ++fields;
  }
  return fields == 4;
}

void PipaSecureProtocol::updateUi(JsonObjectConst object) {
  if (object.isNull()) return;
  const char* state = object["state"] | "idle";
  if (strcmp(state, "idle") == 0 || strcmp(state, "listening") == 0 ||
      strcmp(state, "thinking") == 0 || strcmp(state, "confirm") == 0 ||
      strcmp(state, "speaking") == 0 || strcmp(state, "focus") == 0 ||
      strcmp(state, "dashboard") == 0) {
    ui_.state = state;
  } else {
    ui_.state = "idle";
  }
  const char* caption = object["caption"] | "";
  ui_.caption = isSafeDisplayText(caption, 256) ? String(caption).substring(0, 256) : String();
  transient_idle_started_at_ = 0;
  if (ui_.state != "confirm") {
    ui_.confirmation_id.clear();
    ui_.confirmation_summary.clear();
  }
}

void PipaSecureProtocol::resetHandshake() {
#if PIPA_AUDIO_CAPTURE_ENABLED
  cancelAudioStream();
#endif
  authenticated_ = false;
  handshake_.clear();
  session_.clear();
  ui_.confirmation_id.clear();
  ui_.confirmation_summary.clear();
  ui_.caption.clear();
  ui_.state = "idle";
  transient_idle_started_at_ = 0;
}

void PipaSecureProtocol::log(const String& message) {
  transport_.print("# ");
  transport_.println(message);
}

}  // namespace pipa
