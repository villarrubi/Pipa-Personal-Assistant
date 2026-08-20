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
#include "pipa_secure_session.h"
#include "pipa_secure_protocol.h"
#include "pipa_display.h"
#include "pipa_audio.h"
#include "pipa_power.h"
#include "wake_on_lan.h"

#if PIPA_AUDIO_CAPTURE_ENABLED && !PIPA_SECURE_SESSION_ENABLED
#error "Microphone capture requires the encrypted secure-session-v2 transport."
#endif

#if defined(PIPA_SECURE_SESSION_VECTOR_TEST)
#include "pipa_secure_audio.h"
#endif

namespace {

constexpr uint32_t kTouchDebounceMs = 800;
constexpr uint32_t kWolCooldownMs = 10000;
constexpr uint32_t kWifiRetryMs = 30000;
constexpr uint32_t kPowerSampleMs = 30000;
// The authenticated challenge is already larger than the 256-byte default
// HWCDC queue.  Match the protocol's bounded line size so complete JSON
// frames reach PipaProtocol instead of losing their trailing newline.
constexpr size_t kSerialRxBufferSize = 12 * 1024;
#if PIPA_AUDIO_CAPTURE_ENABLED
constexpr size_t kAudioChunkBytes = 4096;
constexpr uint16_t kMaxAudioChunks = 64;
constexpr uint32_t kMaxCaptureMs = 8000;
#endif

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
#if PIPA_AUDIO_CAPTURE_ENABLED
bool audio_start_pending = false;
bool audio_stop_requested = false;
bool audio_stream_active = false;
uint16_t audio_chunks_sent = 0;
uint32_t audio_started_at = 0;
uint32_t audio_stream_counter = 0;
uint8_t audio_chunk[kAudioChunkBytes] = {};
#endif

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
#if PIPA_AUDIO_CAPTURE_ENABLED
    } else if (audio_stream_active || audio_start_pending || protocol.ui().state == "listening") {
      audio_stop_requested = true;
    } else if (audio.stateMachine().canAdvertiseAudio()) {
      audio_start_pending = protocol.sendHoldStart();
      audio_stop_requested = false;
#endif
    } else {
      protocol.sendGesture("tap");
    }
  } else {
    maybeWakePc();
  }
}

#if PIPA_AUDIO_CAPTURE_ENABLED
void stopAudioCapture(bool transport_ok) {
  memset(audio_chunk, 0, sizeof(audio_chunk));
  if (!transport_ok) protocol.abortAudioStream();
  audio.cancelCapture();
  protocol.setAudioState(audio.stateMachine().state());
  audio_start_pending = false;
  audio_stop_requested = false;
  audio_stream_active = false;
  audio_chunks_sent = 0;
  audio_started_at = 0;
}

void maintainAudioCapture() {
  if (!protocol.authenticated()) {
    if (audio_stream_active || audio_start_pending) stopAudioCapture(false);
    return;
  }

  if (audio_start_pending && !audio_stream_active) {
    if (protocol.ui().state != "listening") return;
    if (!audio.beginCapture(true, true, true)) {
      stopAudioCapture(false);
      return;
    }
    protocol.setAudioState(audio.stateMachine().state());
    String stream_id = "voice-";
    stream_id += String(++audio_stream_counter, HEX);
    stream_id += "-";
    stream_id += String(millis(), HEX);
    if (!protocol.beginAudioStream(stream_id.c_str())) {
      stopAudioCapture(false);
      return;
    }
    audio_stream_active = true;
    audio_started_at = millis();
  }

  if (!audio_stream_active) return;
  const size_t captured = audio.readMonoPcm(audio_chunk, sizeof(audio_chunk));
  if (captured == 0) {
    audio.stateMachine().fail();
    stopAudioCapture(false);
    return;
  }

  const bool final = audio_stop_requested || millis() - audio_started_at >= kMaxCaptureMs ||
      audio_chunks_sent + 1 >= kMaxAudioChunks;
  const bool sent = protocol.sendAudioChunk(audio_chunk, captured, final);
  memset(audio_chunk, 0, sizeof(audio_chunk));
  if (!sent) {
    audio.stateMachine().fail();
    stopAudioCapture(false);
    return;
  }
  ++audio_chunks_sent;
  if (final) {
    if (!audio.finishCapture()) audio.stateMachine().fail();
    protocol.setAudioState(audio.stateMachine().state());
    audio_start_pending = false;
    audio_stop_requested = false;
    audio_stream_active = false;
    audio_chunks_sent = 0;
    audio_started_at = 0;
  }
}
#endif

}  // namespace

void setup() {
  const bool serial_rx_ready =
      Serial.setRxBufferSize(kSerialRxBufferSize) == kSerialRxBufferSize;
  Serial.begin(115200);
  delay(500);
  log(String("Pipa firmware ") + PIPA_FIRMWARE_VERSION + " starting");
  log(String("board revision: ") + PIPA_BOARD_REVISION);
  if (!serial_rx_ready) {
    log("FATAL: USB serial RX buffer could not be allocated");
    return;
  }

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
#if PIPA_AUDIO_CAPTURE_ENABLED
  log(audio.stateMachine().canAdvertiseAudio() ? "audio capture ready" : "audio capture unavailable");
#endif
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
#if PIPA_AUDIO_CAPTURE_ENABLED
  maintainAudioCapture();
#endif
  delay(10);
}
