#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "device_identity.h"
#include "pipa_audio_state.h"

namespace pipa {

struct UiSnapshot {
  String state = "idle";
  String caption;
  String confirmation_id;
  String confirmation_summary;
};

// Result and error captions are informational, not interaction modes. Keep
// them briefly visible and then restore the normal idle face locally even if
// the server has no new event to send.
constexpr uint32_t kTransientIdleCaptionMs = 3000;

class PipaProtocol {
 public:
  PipaProtocol(
      Stream& transport,
      DeviceIdentity& identity,
      const char* device_id,
      const char* firmware_version);

  void begin();
  void poll();
  void maintainUi(uint32_t now_ms);
  bool authenticated() const { return authenticated_; }
  const UiSnapshot& ui() const { return ui_; }

  void setHardwareCapabilities(bool display_ready, bool touch_ready, bool audio_probe_ready);
  void setAudioState(PipaAudioState state);
  void setBatteryPercent(int battery_percent);

  void sendGesture(const char* gesture);
  void sendTextInput(const char* text, const char* source = "voice");
  void sendConfirmation(bool accepted);

 private:
  static constexpr size_t kMaxInboundLine = 12000;
  static constexpr size_t kMaxOutboundLine = 12000;
  static constexpr size_t kMaxTextInput = 4000;
  static constexpr uint32_t kChallengeRetryMs = 5000;
  static constexpr uint32_t kHeartbeatMs = 30000;
  static constexpr uint32_t kStatusMs = 60000;
  static constexpr uint32_t kServerTimeoutMs = 90000;

  void readTransport();
  void handleLine(const String& line);
  void handleMessage(JsonDocument& document);
  bool validateChallenge(JsonObject challenge) const;
  void sendChallengeRequest();
  void sendSignedHello(JsonObject challenge);
  void sendHeartbeat();
  void sendDeviceStatus();
  void updateUi(JsonObject object);
  void clearSessionUi();
  void sendJson(JsonDocument& document);
  void log(const String& message);

  Stream& transport_;
  DeviceIdentity& identity_;
  const char* device_id_;
  const char* firmware_version_;
  UiSnapshot ui_;
  String inbound_line_;
  bool dropping_oversized_line_ = false;
  bool awaiting_ready_ = false;
  bool authenticated_ = false;
  bool display_ready_ = false;
  bool touch_ready_ = false;
  bool audio_probe_ready_ = false;
  PipaAudioState audio_state_ = PipaAudioState::kDisabled;
  int battery_percent_ = -1;
  uint32_t last_challenge_request_ = 0;
  uint32_t last_heartbeat_ = 0;
  uint32_t last_status_ = 0;
  uint32_t last_server_message_ = 0;
  uint32_t transient_idle_started_at_ = 0;
};

}  // namespace pipa
