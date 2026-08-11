#include <Arduino.h>
#include <ArduinoJson.h>
#include <Crypto.h>
#include <Ed25519.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "cst816_touch.h"
#if __has_include("pipa_device_config.local.h")
#include "pipa_device_config.local.h"
#else
#include "pipa_device_config.h"
#endif
#include "wake_on_lan.h"

namespace {

constexpr uint32_t kChallengeRetryMs = 5000;
constexpr int kTouchSda = 1;
constexpr int kTouchScl = 3;

Preferences preferences;
WiFiUDP udp;
pipa::WakeOnLan wake_on_lan(udp);
pipa::Cst816Touch touch;
uint8_t private_key[32] = {};
uint8_t public_key[32] = {};
bool authenticated = false;
uint32_t last_challenge_request = 0;
uint32_t last_touch = 0;

String toBase64Url(const uint8_t* bytes, size_t length) {
  static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  String value;
  value.reserve(((length + 2) / 3) * 4);
  for (size_t index = 0; index < length; index += 3) {
    const uint32_t block = static_cast<uint32_t>(bytes[index]) << 16 |
                           static_cast<uint32_t>(index + 1 < length ? bytes[index + 1] : 0) << 8 |
                           static_cast<uint32_t>(index + 2 < length ? bytes[index + 2] : 0);
    value += alphabet[(block >> 18) & 0x3F];
    value += alphabet[(block >> 12) & 0x3F];
    if (index + 1 < length) value += alphabet[(block >> 6) & 0x3F];
    if (index + 2 < length) value += alphabet[block & 0x3F];
  }
  return value;
}

void loadIdentity() {
  preferences.begin("pipa", false);
  if (preferences.getBytesLength("private") == sizeof(private_key) &&
      preferences.getBytes("private", private_key, sizeof(private_key)) == sizeof(private_key)) {
    Ed25519::derivePublicKey(public_key, private_key);
    return;
  }

  Ed25519::generatePrivateKey(private_key);
  Ed25519::derivePublicKey(public_key, private_key);
  preferences.putBytes("private", private_key, sizeof(private_key));
  Serial.println("PIPA_IDENTITY_CREATED: pair this device using the public key below");
}

void sendJson(JsonDocument& document) {
  serializeJson(document, Serial);
  Serial.println();
}

void sendChallengeRequest() {
  JsonDocument document;
  document["protocol_version"] = 1;
  document["type"] = "challenge_request";
  document["device_id"] = PIPA_DEVICE_ID;
  sendJson(document);
}

void sendSignedHello(JsonObject challenge) {
  JsonDocument canonical;
  // This insertion order mirrors Python's sort_keys=True contract.
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
  uint8_t signature[64] = {};
  Ed25519::sign(signature, private_key, public_key, signing_bytes.c_str(), signing_bytes.length());

  JsonDocument response;
  response["protocol_version"] = 1;
  response["type"] = "hello";
  response["device_id"] = PIPA_DEVICE_ID;
  response["challenge_id"] = challenge["challenge_id"];
  response["signature"] = toBase64Url(signature, sizeof(signature));
  sendJson(response);
}

void handleMessage(const String& line) {
  JsonDocument document;
  if (deserializeJson(document, line) != DeserializationError::Ok) return;

  const char* type = document["type"] | "";
  if (strcmp(type, "challenge") == 0) {
    JsonObject challenge = document["challenge"].as<JsonObject>();
    if (!challenge.isNull()) sendSignedHello(challenge);
  } else if (strcmp(type, "ready") == 0) {
    authenticated = true;
    Serial.println("PIPA_READY");
  } else if (strcmp(type, "error") == 0) {
    authenticated = false;
  }
}

void connectWifi() {
  if (strlen(PIPA_WIFI_SSID) == 0) {
    Serial.println("PIPA_WIFI_NOT_CONFIGURED");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.begin(PIPA_WIFI_SSID, PIPA_WIFI_PASSWORD);
  const uint32_t deadline = millis() + 15000;
  while (WiFi.status() != WL_CONNECTED && millis() < deadline) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("PIPA_WIFI_READY ");
    Serial.println(WiFi.localIP());
    udp.begin(9);
  } else {
    Serial.println("PIPA_WIFI_FAILED");
  }
}

void maybeWakePc() {
  if (WiFi.status() != WL_CONNECTED) return;
  const bool sent = wake_on_lan.send(PIPA_PC_MAC);
  Serial.println(sent ? "PIPA_WOL_SENT" : "PIPA_WOL_FAILED");
}

void pollTouch() {
  pipa::TouchPoint point;
  if (!touch.read(point) || millis() - last_touch < 800) return;
  last_touch = millis();
  Serial.printf("PIPA_TOUCH %u %u\n", point.x, point.y);
  maybeWakePc();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.printf("PIPA Waveshare ESP32-S3-Touch-LCD-1.85C firmware %s\n", PIPA_FIRMWARE_VERSION);
  loadIdentity();
  Serial.print("PIPA_PUBLIC_KEY=");
  Serial.println(toBase64Url(public_key, sizeof(public_key)));
  connectWifi();
  Wire.begin(kTouchSda, kTouchScl);
  touch.begin(Wire);
  sendChallengeRequest();
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0 && line.length() < 12000) handleMessage(line);
  }
  if (!authenticated && millis() - last_challenge_request >= kChallengeRetryMs) {
    last_challenge_request = millis();
    sendChallengeRequest();
  }
  pollTouch();
  delay(20);
}
