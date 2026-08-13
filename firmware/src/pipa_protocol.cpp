#include "pipa_protocol.h"

#include <WiFi.h>

#include "pipa_text_policy.h"

namespace pipa {

PipaProtocol::PipaProtocol(
    Stream& transport,
    DeviceIdentity& identity,
    const char* device_id,
    const char* firmware_version)
    : transport_(transport),
      identity_(identity),
      device_id_(device_id),
      firmware_version_(firmware_version) {
  inbound_line_.reserve(1024);
}

void PipaProtocol::begin() {
  last_challenge_request_ = millis();
  sendChallengeRequest();
}

void PipaProtocol::setHardwareCapabilities(
    bool display_ready,
    bool touch_ready,
    bool audio_probe_ready) {
  display_ready_ = display_ready;
  touch_ready_ = touch_ready;
  audio_probe_ready_ = audio_probe_ready;
}

void PipaProtocol::setAudioState(PipaAudioState state) {
  audio_state_ = state;
}

void PipaProtocol::setBatteryPercent(int battery_percent) {
  battery_percent_ = battery_percent >= 0 && battery_percent <= 100 ? battery_percent : -1;
}

void PipaProtocol::poll() {
  readTransport();
  const uint32_t now = millis();
  if (authenticated_ && now - last_server_message_ >= kServerTimeoutMs) {
    authenticated_ = false;
    awaiting_ready_ = false;
    log("server heartbeat timed out; authenticating again");
    last_challenge_request_ = now;
    sendChallengeRequest();
    return;
  }
  if (!authenticated_ && now - last_challenge_request_ >= kChallengeRetryMs) {
    last_challenge_request_ = now;
    sendChallengeRequest();
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

void PipaProtocol::sendGesture(const char* gesture) {
  if (!authenticated_ || !isSafeGesture(gesture)) return;
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "gesture";
  document["gesture"] = gesture;
  sendJson(document);
}

void PipaProtocol::sendTextInput(const char* text, const char* source) {
  const char* safe_source = source == nullptr || source[0] == '\0' ? "unknown" : source;
  if (!authenticated_ || !isSafeDisplayText(text, kMaxTextInput) ||
      !isSafeTextSource(safe_source)) {
    if (authenticated_ && text != nullptr && strlen(text) > kMaxTextInput) {
      log("outgoing text discarded: too large");
    }
    return;
  }
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "text_input";
  document["text"] = text;
  document["source"] = safe_source;
  sendJson(document);
}

void PipaProtocol::sendConfirmation(bool accepted) {
  if (!authenticated_ || ui_.confirmation_id.isEmpty() || ui_.confirmation_summary.isEmpty()) return;
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "confirm";
  document["confirmation_id"] = ui_.confirmation_id;
  document["accepted"] = accepted;
  sendJson(document);
}

void PipaProtocol::readTransport() {
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
      log("incoming message discarded: too large");
      continue;
    }
    inbound_line_ += character;
  }
}

void PipaProtocol::handleLine(const String& line) {
  JsonDocument document;
  if (deserializeJson(document, line) != DeserializationError::Ok) {
    log("incoming message discarded: invalid JSON");
    return;
  }
  handleMessage(document);
}

void PipaProtocol::handleMessage(JsonDocument& document) {
  const int protocol_version = document["protocol_version"] | 0;
  if (protocol_version != 1) {
    log("server protocol version rejected");
    return;
  }
  const char* type = document["type"] | "";
  if (strcmp(type, "challenge") == 0) {
    if (authenticated_ || awaiting_ready_) {
      log("unexpected challenge discarded");
      return;
    }
    JsonObject challenge = document["challenge"].as<JsonObject>();
    if (!validateChallenge(challenge)) {
      log("invalid challenge discarded");
      return;
    }
    last_server_message_ = millis();
    sendSignedHello(challenge);
  } else if (strcmp(type, "ready") == 0) {
    const char* session_id = document["session_id"] | "";
    if (!awaiting_ready_ || session_id[0] == '\0' || strlen(session_id) > 128) {
      log("unexpected ready message discarded");
      return;
    }
    awaiting_ready_ = false;
    authenticated_ = true;
    last_server_message_ = millis();
    last_heartbeat_ = millis();
    last_status_ = last_heartbeat_;
    JsonObject nested_ui = document["ui_state"].as<JsonObject>();
    if (!nested_ui.isNull()) updateUi(nested_ui);
    sendDeviceStatus();
    log("authenticated session ready");
  } else if (strcmp(type, "ui_state") == 0) {
    if (!authenticated_) return;
    last_server_message_ = millis();
    updateUi(document.as<JsonObject>());
  } else if (strcmp(type, "confirm_request") == 0) {
    if (!authenticated_) return;
    if (!ui_.confirmation_id.isEmpty()) {
      log("confirmation request discarded: another confirmation is visible");
      return;
    }
    const char* confirmation_id = document["confirmation_id"] | "";
    const char* summary = document["summary"] | "";
    if (!isSafeDisplayText(confirmation_id, 128) || !isSafeDisplayText(summary, 256)) {
      log("invalid confirmation request discarded");
      return;
    }
    last_server_message_ = millis();
    ui_.confirmation_id = confirmation_id;
    ui_.confirmation_summary = summary;
    ui_.state = "confirm";
  } else if (strcmp(type, "tool_result") == 0) {
    if (!authenticated_) return;
    last_server_message_ = millis();
    ui_.confirmation_id.clear();
    ui_.confirmation_summary.clear();
  } else if (strcmp(type, "pong") == 0 || strcmp(type, "status_ack") == 0 ||
             strcmp(type, "gesture_ack") == 0 || strcmp(type, "tts_aborted") == 0) {
    if (!authenticated_) return;
    last_server_message_ = millis();
  } else if (strcmp(type, "error") == 0) {
    last_server_message_ = millis();
    const char* code = document["code"] | "unknown";
    if (strcmp(code, "authentication_failed") == 0 || strcmp(code, "authentication_required") == 0 ||
        strcmp(code, "unknown_session") == 0) {
      authenticated_ = false;
      awaiting_ready_ = false;
      last_challenge_request_ = millis();
      sendChallengeRequest();
    }
    log(String("server error: ") + code);
  } else {
    log("unknown server message discarded");
  }
}

bool PipaProtocol::validateChallenge(JsonObject challenge) const {
  if (challenge.isNull()) return false;
  const char* audience = challenge["audience"] | "";
  const char* device_id = challenge["device_id"] | "";
  const char* operation = challenge["operation"] | "";
  const char* challenge_id = challenge["challenge_id"] | "";
  const char* nonce = challenge["nonce"] | "";
  const int protocol_version = challenge["protocol_version"] | 0;
  if (!challenge["issued_at"].is<int64_t>() || !challenge["expires_at"].is<int64_t>()) return false;
  const int64_t issued_at = challenge["issued_at"].as<int64_t>();
  const int64_t expires_at = challenge["expires_at"].as<int64_t>();
  return protocol_version == 1 &&
         strcmp(audience, "pipa-trusted-unlock") == 0 &&
         strcmp(device_id, device_id_) == 0 &&
         strcmp(operation, "session") == 0 &&
         challenge_id[0] != '\0' && strlen(challenge_id) <= 128 &&
         nonce[0] != '\0' && strlen(nonce) <= 128 &&
         issued_at > 0 && expires_at > issued_at && expires_at - issued_at <= 300;
}

void PipaProtocol::sendChallengeRequest() {
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "challenge_request";
  document["device_id"] = device_id_;
  sendJson(document);
}

void PipaProtocol::sendSignedHello(JsonObject challenge) {
  JsonDocument canonical;
  // This insertion order mirrors Python json.dumps(sort_keys=True).
  canonical["audience"] = challenge["audience"];
  canonical["challenge_id"] = challenge["challenge_id"];
  canonical["device_id"] = challenge["device_id"];
  canonical["expires_at"] = challenge["expires_at"];
  canonical["issued_at"] = challenge["issued_at"];
  canonical["nonce"] = challenge["nonce"];
  canonical["operation"] = challenge["operation"];
  canonical["protocol_version"] = challenge["protocol_version"];

  String signing_bytes;
  serializeJson(canonical, signing_bytes);
  const String signature = identity_.signBase64Url(signing_bytes);
  if (signature.isEmpty()) {
    log("challenge signing failed");
    return;
  }

  JsonDocument response;
  response["protocol_version"] = 1;
  response["type"] = "hello";
  response["device_id"] = device_id_;
  response["challenge_id"] = challenge["challenge_id"];
  response["signature"] = signature;
  response["firmware_version"] = firmware_version_;
  JsonArray capabilities = response["capabilities"].to<JsonArray>();
  capabilities.add("usb_serial");
  if (touch_ready_) capabilities.add("touch");
  if (display_ready_) capabilities.add("display");
  if (audio_probe_ready_) capabilities.add("audio_probe");
  capabilities.add("wol");
  capabilities.add("text_input");
  capabilities.add("device_status");
  sendJson(response);
  awaiting_ready_ = true;
}

void PipaProtocol::sendHeartbeat() {
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "ping";
  document["request_id"] = String(millis(), HEX);
  sendJson(document);
}

void PipaProtocol::sendDeviceStatus() {
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "device_status";
  document["audio_state"] = pipaAudioStateName(audio_state_);
  if (battery_percent_ >= 0) document["battery_percent"] = battery_percent_;
  if (WiFi.status() == WL_CONNECTED) document["wifi_rssi"] = WiFi.RSSI();
  sendJson(document);
}

void PipaProtocol::updateUi(JsonObject object) {
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
  if (ui_.state != "confirm") {
    ui_.confirmation_id.clear();
    ui_.confirmation_summary.clear();
  }
}

void PipaProtocol::sendJson(JsonDocument& document) {
  if (measureJson(document) + 1 > kMaxOutboundLine) {
    log("outgoing message discarded: too large");
    return;
  }
  serializeJson(document, transport_);
  transport_.print('\n');
}

void PipaProtocol::log(const String& message) {
  transport_.print("# ");
  transport_.println(message);
}

}  // namespace pipa
