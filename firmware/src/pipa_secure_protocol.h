#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "device_identity.h"
#include "pipa_protocol.h"
#include "pipa_secure_handshake.h"
#include "pipa_secure_session.h"
#if PIPA_AUDIO_CAPTURE_ENABLED
#include "pipa_secure_audio.h"
#endif

namespace pipa {

// Encrypted counterpart of PipaProtocol. It mirrors the device-facing UI and
// capability announcement; all Core commands remain validated by Python.
class PipaSecureProtocol {
 public:
  PipaSecureProtocol(
      Stream& transport,
      DeviceIdentity& identity,
      const char* device_id,
      const char* firmware_version,
      const char* server_id,
      const char* server_public_key);

  void begin();
  void poll();
  bool authenticated() const { return authenticated_; }
  const UiSnapshot& ui() const { return ui_; }

  void setHardwareCapabilities(bool display_ready, bool touch_ready, bool audio_probe_ready);
  void setAudioState(PipaAudioState state);
  void setBatteryPercent(int battery_percent);

  void sendGesture(const char* gesture);
  void sendTextInput(const char* text, const char* source = "voice");
  void sendConfirmation(bool accepted);
#if PIPA_AUDIO_CAPTURE_ENABLED
  bool sendHoldStart();
  bool beginAudioStream(const char* stream_id);
  bool sendAudioChunk(const uint8_t* samples, size_t samples_length, bool final);
  void abortAudioStream();
  void cancelAudioStream();
#endif

 private:
  static constexpr size_t kMaxInboundLine = 12000;
  static constexpr size_t kMaxOutboundLine = 12000;
  static constexpr size_t kMaxPlaintext = 6000;
  static constexpr size_t kMaxCiphertext = kMaxOutboundLine;
  static constexpr size_t kMaxKeyBytes = 32;
  static constexpr uint32_t kHandshakeRetryMs = 5000;
  static constexpr uint32_t kHeartbeatMs = 30000;
  static constexpr uint32_t kStatusMs = 60000;
  static constexpr uint32_t kServerTimeoutMs = 90000;

  void readTransport();
  void handleLine(const String& line);
  void handleServerHello(JsonObjectConst object);
  void handleEncryptedFrame(JsonObjectConst object);
  void rejectEncryptedFrame(const char* reason);
  void handleMessage(JsonObjectConst object);
  void sendHandshake();
  void sendDeviceHello();
  void sendHeartbeat();
  void sendDeviceStatus();
  void sendJson(JsonDocument& document);
  void sendEncrypted(JsonDocument& document);
  bool decodeServerKey(uint8_t output[kMaxKeyBytes]) const;
  static bool decodeBase64Url(
      const char* value,
      uint8_t* output,
      size_t output_capacity,
      size_t* decoded_length = nullptr);
  static String encodeBase64Url(const uint8_t* bytes, size_t length);
  static bool frameHasExactFields(JsonObjectConst object);
  void updateUi(JsonObjectConst object);
  void resetHandshake();
  void log(const String& message);

  Stream& transport_;
  DeviceIdentity& identity_;
  const char* device_id_;
  const char* firmware_version_;
  const char* server_id_;
  const char* server_public_key_;
  PipaSecureHandshake handshake_;
  PipaSecureSession session_;
  UiSnapshot ui_;
  String inbound_line_;
  bool dropping_oversized_line_ = false;
  bool authenticated_ = false;
  bool display_ready_ = false;
  bool touch_ready_ = false;
  bool audio_probe_ready_ = false;
  PipaAudioState audio_state_ = PipaAudioState::kDisabled;
  int battery_percent_ = -1;
  uint32_t last_handshake_ = 0;
  uint32_t last_heartbeat_ = 0;
  uint32_t last_status_ = 0;
  uint32_t last_server_message_ = 0;
#if PIPA_AUDIO_CAPTURE_ENABLED
  PipaSecureAudioSender* audio_sender_ = nullptr;
#endif
};

}  // namespace pipa
