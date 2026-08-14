#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "cst816_touch.h"
#include "device_identity.h"
#if __has_include("pipa_device_config.local.h")
#include "pipa_device_config.local.h"
#else
#include "pipa_device_config.h"
#endif
#include "board_pins.h"
#include "pipa_audio_state.h"
#include "pipa_protocol.h"
#include "pipa_secure_audio.h"
#include "pipa_secure_session.h"
#include "pipa_secure_protocol.h"
#include "pipa_display.h"
#include "pipa_audio.h"
#include "pipa_power.h"
#include "wake_on_lan.h"

namespace {

constexpr uint32_t kTouchDebounceMs = 800;
constexpr uint32_t kWolCooldownMs = 10000;
constexpr uint32_t kWifiRetryMs = 30000;
constexpr uint32_t kPowerSampleMs = 30000;

pipa::DeviceIdentity identity;
#if PIPA_SECURE_SESSION_ENABLED
pipa::PipaSecureProtocol protocol(
    Serial,
    identity,
    PIPA_DEVICE_ID,
    PIPA_FIRMWARE_VERSION,
    PIPA_SECURE_SERVER_ID,
    PIPA_SECURE_SERVER_PUBLIC_KEY);
#else
pipa::PipaProtocol protocol(Serial, identity, PIPA_DEVICE_ID, PIPA_FIRMWARE_VERSION);
#endif
pipa::Tca9554 io_expander;
WiFiUDP udp;
pipa::WakeOnLan wake_on_lan(udp);
pipa::Cst816Touch touch;
pipa::PipaDisplay display;
pipa::PipaAudio audio;
pipa::PipaPower power;
uint32_t last_touch = 0;
uint32_t last_wol = 0;
uint32_t last_wifi_attempt = 0;
uint32_t last_power_sample = 0;
bool wifi_online = false;
bool firmware_ready = false;

void log(const String& message) {
  Serial.print("# ");
  Serial.println(message);
}

void startWifiConnection() {
  if (strlen(PIPA_WIFI_SSID) == 0) {
    log("Wi-Fi not configured; Wake-on-LAN disabled");
    return;
  }
  last_wifi_attempt = millis();
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.disconnect();
  WiFi.begin(PIPA_WIFI_SSID, PIPA_WIFI_PASSWORD);
  log("Wi-Fi connection started");
}

void maintainWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifi_online) {
      wifi_online = true;
      udp.begin(9);
      // The serial monitor is an operational channel, not a network
      // diagnostic. Do not expose the local address in logs or captured
      // boot output.
      log("Wi-Fi ready");
    }
    return;
  }
  if (wifi_online) {
    wifi_online = false;
    udp.stop();
    log("Wi-Fi connection lost");
  }
  if (strlen(PIPA_WIFI_SSID) != 0 && millis() - last_wifi_attempt >= kWifiRetryMs) {
    startWifiConnection();
  }
}

void maintainPower() {
  const uint32_t now = millis();
  if (last_power_sample != 0 && now - last_power_sample < kPowerSampleMs) return;
  last_power_sample = now;
  power.update();
  protocol.setBatteryPercent(power.batteryPercent());
}

void maybeWakePc() {
  if (WiFi.status() != WL_CONNECTED) {
    log("Wake-on-LAN ignored: Wi-Fi offline");
    return;
  }
  if (last_wol != 0 && millis() - last_wol < kWolCooldownMs) return;
  last_wol = millis();
  log(wake_on_lan.send(PIPA_PC_MAC) ? "Wake-on-LAN sent" : "Wake-on-LAN failed");
}

void pollTouch() {
  pipa::TouchPoint point;
  if (!touch.read(point) || (last_touch != 0 && millis() - last_touch < kTouchDebounceMs)) return;
  last_touch = millis();
  if (protocol.authenticated()) {
    if (protocol.ui().state == "confirm") {
      protocol.sendConfirmation(true);
    } else {
      protocol.sendGesture("tap");
    }
  } else {
    maybeWakePc();
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(500);
  log(String("Pipa firmware ") + PIPA_FIRMWARE_VERSION + " starting");
  log(String("board revision: ") + PIPA_BOARD_REVISION);

#if defined(PIPA_SECURE_SESSION_VECTOR_TEST)
  log((pipa::PipaSecureSession::vectorSelfTest() &&
       pipa::PipaSecureAudio::vectorSelfTest() &&
       pipa::PipaAudioStateMachine::vectorSelfTest())
          ? "secure session vector: PASS"
          : "secure session vector: FAIL");
#endif

  if (!identity.begin()) {
    log("FATAL: device identity could not be loaded or created");
    return;
  }
  log(String("PIPA_PUBLIC_KEY=") + identity.publicKeyBase64Url());

  startWifiConnection();
  Wire.begin(pipa::board::kI2cSda, pipa::board::kI2cScl);
  const bool expander_ready = io_expander.begin(Wire);
  log(expander_ready ? "IO expander ready" : "IO expander unavailable");
  const bool display_ready = display.begin(expander_ready ? &io_expander : nullptr);
  log(display_ready ? "display ready" : "display unavailable");
  const bool audio_probe_ready = audio.begin(Wire);
  const auto& audio_status = audio.status();
  log(audio_probe_ready ? "audio codec probe ready" : "audio codecs not detected");
  log(String("audio output ES8311: ") + (audio_status.output_codec_present ? "present" : "absent"));
  log(String("audio input ES7210: ") + (audio_status.input_codec_present ? "present" : "absent"));
  const bool power_ready = power.begin();
  log(power_ready ? "battery ADC ready" : "battery ADC unavailable for this board revision");
  protocol.setBatteryPercent(power.batteryPercent());
  const bool touch_ready = touch.begin(
      Wire,
      0x15,
      expander_ready ? &io_expander : nullptr,
      pipa::board::kTouchResetExpander,
      pipa::board::kTouchInterrupt);
  log(touch_ready ? "touch controller ready" : "touch controller unavailable");
  protocol.setHardwareCapabilities(display_ready, touch_ready, audio_probe_ready);
  protocol.setAudioState(audio_status.state);
  protocol.begin();
  firmware_ready = true;
}

void loop() {
  if (!firmware_ready) {
    delay(1000);
    return;
  }
  protocol.poll();
  display.render(protocol.ui());
  maintainWifi();
  maintainPower();
  pollTouch();
  delay(10);
}
