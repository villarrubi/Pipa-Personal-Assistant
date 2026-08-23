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
#include "pipa_local_wake.h"
#include "pipa_voice_activity.h"
#include "pipa_power.h"
#include "wake_on_lan.h"

#if PIPA_ALWAYS_LISTENING_ENABLED
#include <esp_heap_caps.h>
#endif

#if PIPA_AUDIO_CAPTURE_ENABLED && !PIPA_SECURE_SESSION_ENABLED
#error "Microphone capture requires the encrypted secure-session-v2 transport."
#endif
#if PIPA_ALWAYS_LISTENING_ENABLED && !PIPA_AUDIO_CAPTURE_ENABLED
#error "Hands-free monitoring requires the encrypted microphone capture path."
#endif
#if PIPA_ALWAYS_LISTENING_ENABLED && !PIPA_LOCAL_WAKE_PHRASE_ENABLED
#error "Hands-free monitoring requires an offline activation-phrase gate."
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
// Whisper is much more reliable when a short wake-only utterance includes a
// little trailing silence.  Keep the capture open briefly after VAD ends so
// "Pipa me escuchas" is not reduced to a one-second fragment.
constexpr uint32_t kMinimumCaptureMs = 1800;
#if PIPA_ALWAYS_LISTENING_ENABLED
constexpr uint16_t kMaxAudioChunks = 256;
constexpr uint32_t kMaxCaptureMs = 8000;
constexpr uint32_t kInstructionStartTimeoutMs = 2000;
// Volatile rolling context long enough to include the activation phrase. It
// is overwritten locally and is released to the encrypted stream only after
// the offline recognizer has fired.
constexpr uint8_t kPreRollChunks = 16;
// MultiNet should see the whole phrase, including a softly spoken first
// syllable.  The rolling buffer already keeps two seconds of context; use it
// all for the local recognizer instead of feeding it only the last second.
constexpr uint8_t kLocalWakeModelPreRollChunks = kPreRollChunks;
constexpr size_t kDeferredAudioBytes = kMaxAudioChunks * kAudioChunkBytes;
#else
constexpr uint16_t kMaxAudioChunks = 64;
constexpr uint32_t kMaxCaptureMs = 8000;
#endif
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
bool audio_speech_ended = false;
uint16_t audio_chunks_sent = 0;
uint32_t audio_started_at = 0;
uint32_t audio_stream_counter = 0;
alignas(int16_t) uint8_t audio_chunk[kAudioChunkBytes] = {};
#if PIPA_ALWAYS_LISTENING_ENABLED
pipa::PipaVoiceActivityDetector voice_activity;
pipa::PipaLocalWakePhrase local_wake_phrase;
uint8_t pre_roll[kPreRollChunks][kAudioChunkBytes] = {};
size_t pre_roll_lengths[kPreRollChunks] = {};
uint8_t pre_roll_next = 0;
uint8_t pre_roll_count = 0;
uint8_t* deferred_audio = nullptr;
size_t deferred_audio_length = 0;
size_t deferred_upload_offset = 0;
uint32_t deferred_capture_started_at = 0;
bool deferred_capture_active = false;
bool deferred_capture_ready = false;
bool deferred_upload_pending = false;
#endif
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
#if PIPA_ALWAYS_LISTENING_ENABLED
    } else {
      protocol.sendGesture("tap");
#else
    } else if (audio.stateMachine().canAdvertiseAudio()) {
      audio_start_pending = protocol.sendHoldStart();
      audio_stop_requested = false;
    } else {
      protocol.sendGesture("tap");
#endif
#else
    } else {
      protocol.sendGesture("tap");
#endif
    }
  } else {
    maybeWakePc();
  }
}

#if PIPA_AUDIO_CAPTURE_ENABLED
#if PIPA_ALWAYS_LISTENING_ENABLED
void clearPreRoll() {
  memset(pre_roll, 0, sizeof(pre_roll));
  memset(pre_roll_lengths, 0, sizeof(pre_roll_lengths));
  pre_roll_next = 0;
  pre_roll_count = 0;
}

void rememberPreRoll(const uint8_t* samples, size_t length) {
  if (samples == nullptr || length == 0 || length > kAudioChunkBytes) return;
  memset(pre_roll[pre_roll_next], 0, kAudioChunkBytes);
  memcpy(pre_roll[pre_roll_next], samples, length);
  pre_roll_lengths[pre_roll_next] = length;
  pre_roll_next = static_cast<uint8_t>((pre_roll_next + 1) % kPreRollChunks);
  if (pre_roll_count < kPreRollChunks) ++pre_roll_count;
}

void clearDeferredAudio() {
  if (deferred_audio != nullptr && deferred_audio_length > 0) {
    memset(deferred_audio, 0, deferred_audio_length);
  }
  deferred_audio_length = 0;
  deferred_upload_offset = 0;
  deferred_capture_started_at = 0;
  deferred_capture_active = false;
  deferred_capture_ready = false;
  deferred_upload_pending = false;
}

bool appendDeferredAudio(const uint8_t* samples, size_t length) {
  if (deferred_audio == nullptr || samples == nullptr || length == 0 ||
      length % sizeof(int16_t) != 0 ||
      deferred_audio_length + length > kDeferredAudioBytes) {
    return false;
  }
  memcpy(deferred_audio + deferred_audio_length, samples, length);
  deferred_audio_length += length;
  return true;
}

bool movePreRollToDeferredAudio() {
  const uint8_t first = static_cast<uint8_t>(
      (pre_roll_next + kPreRollChunks - pre_roll_count) % kPreRollChunks);
  for (uint8_t offset = 0; offset < pre_roll_count; ++offset) {
    const uint8_t index = static_cast<uint8_t>((first + offset) % kPreRollChunks);
    if (!appendDeferredAudio(pre_roll[index], pre_roll_lengths[index])) {
      clearPreRoll();
      return false;
    }
  }
  clearPreRoll();
  return deferred_audio_length > 0;
}

bool sendPreRoll() {
  const uint8_t first = static_cast<uint8_t>(
      (pre_roll_next + kPreRollChunks - pre_roll_count) % kPreRollChunks);
  for (uint8_t offset = 0; offset < pre_roll_count; ++offset) {
    const uint8_t index = static_cast<uint8_t>((first + offset) % kPreRollChunks);
    const size_t length = pre_roll_lengths[index];
    if (length == 0 || audio_chunks_sent >= kMaxAudioChunks ||
        !protocol.sendAudioChunk(pre_roll[index], length, false)) {
      return false;
    }
    ++audio_chunks_sent;
  }
  clearPreRoll();
  return true;
}

bool detectLocalWakePhraseInPreRoll() {
  const uint8_t model_chunks = min(pre_roll_count, kLocalWakeModelPreRollChunks);
  const uint8_t first = static_cast<uint8_t>(
      (pre_roll_next + kPreRollChunks - model_chunks) % kPreRollChunks);
  for (uint8_t offset = 0; offset < model_chunks; ++offset) {
    const uint8_t index = static_cast<uint8_t>((first + offset) % kPreRollChunks);
    const size_t length = pre_roll_lengths[index];
    if (length == 0) continue;
    if (local_wake_phrase.process(
            reinterpret_cast<const int16_t*>(pre_roll[index]),
            length / sizeof(int16_t))) {
      return true;
    }
  }
  return false;
}

void maintainHandsFreeMonitor() {
  if (deferred_capture_active) {
    const size_t captured = audio.readMonitorMonoPcm(audio_chunk, sizeof(audio_chunk));
    if (captured == 0) return;
    const bool appended = appendDeferredAudio(audio_chunk, captured);
    const auto event = voice_activity.process(
        reinterpret_cast<const int16_t*>(audio_chunk), captured / sizeof(int16_t));
    memset(audio_chunk, 0, sizeof(audio_chunk));
    const bool no_instruction = !voice_activity.speechActive() &&
        millis() - deferred_capture_started_at >= kInstructionStartTimeoutMs;
    if (!appended || event == pipa::PipaVoiceActivityEvent::kSpeechEnded || no_instruction ||
        millis() - deferred_capture_started_at >= kMaxCaptureMs) {
      deferred_capture_active = false;
      deferred_capture_ready = deferred_audio_length > 0;
      deferred_capture_started_at = 0;
      voice_activity.resetUtterance();
      clearPreRoll();
    }
    return;
  }

  if (deferred_capture_ready) {
    if (protocol.authenticated() && protocol.ui().state == "idle" && audio.canMonitor()) {
      audio_start_pending = protocol.sendHoldStart();
      deferred_upload_pending = audio_start_pending;
      audio_stop_requested = false;
    }
    return;
  }

  if (audio_start_pending || audio_stream_active) return;
  if (!local_wake_phrase.ready() || !audio.canMonitor() ||
      (protocol.authenticated() && protocol.ui().state != "idle") ||
      (!protocol.authenticated() && WiFi.status() != WL_CONNECTED)) {
    local_wake_phrase.reset();
    voice_activity.resetUtterance();
    clearPreRoll();
    return;
  }
  const size_t captured = audio.readMonitorMonoPcm(audio_chunk, sizeof(audio_chunk));
  if (captured == 0) return;
  rememberPreRoll(audio_chunk, captured);
  const auto event = voice_activity.process(
      reinterpret_cast<const int16_t*>(audio_chunk), captured / sizeof(int16_t));
  bool activated = false;
  if (event == pipa::PipaVoiceActivityEvent::kSpeechStarted) {
    local_wake_phrase.reset();
    activated = detectLocalWakePhraseInPreRoll();
#if PIPA_SERVER_WAKE_PHRASE_FALLBACK_ENABLED
    // MultiNet only ships an English acoustic model on this board and can
    // intermittently miss the Spanish wake phrase. When the authenticated
    // local agent is available, let its stronger Spanish STT verify the wake
    // phrase instead. This fallback never wakes a powered-off PC and the core
    // still discards speech that does not contain the configured phrase.
    if (!activated && protocol.authenticated()) activated = true;
#endif
  } else if (event == pipa::PipaVoiceActivityEvent::kSpeech ||
             event == pipa::PipaVoiceActivityEvent::kSpeechEnded) {
    activated = local_wake_phrase.process(
        reinterpret_cast<const int16_t*>(audio_chunk), captured / sizeof(int16_t));
  }
  memset(audio_chunk, 0, sizeof(audio_chunk));
  if (activated) {
    local_wake_phrase.reset();
    if (protocol.authenticated()) {
      audio_start_pending = protocol.sendHoldStart();
      audio_stop_requested = false;
      if (!audio_start_pending) {
        voice_activity.resetUtterance();
        clearPreRoll();
      }
    } else {
      clearDeferredAudio();
      if (movePreRollToDeferredAudio()) {
        deferred_capture_active = true;
        deferred_capture_started_at = millis();
        maybeWakePc();
      } else {
        voice_activity.resetUtterance();
      }
    }
  } else if (event == pipa::PipaVoiceActivityEvent::kSpeechEnded) {
    local_wake_phrase.reset();
    voice_activity.resetUtterance();
    clearPreRoll();
  }
}

void finishAudioCapture() {
  if (!audio.finishCapture()) audio.stateMachine().fail();
  protocol.setAudioState(audio.stateMachine().state());
  audio_start_pending = false;
  audio_stop_requested = false;
  audio_stream_active = false;
  audio_speech_ended = false;
  audio_chunks_sent = 0;
  audio_started_at = 0;
  voice_activity.resetUtterance();
  clearPreRoll();
  if (deferred_upload_pending || deferred_capture_ready) {
    clearDeferredAudio();
  }
}
#endif

void stopAudioCapture(bool transport_ok) {
  memset(audio_chunk, 0, sizeof(audio_chunk));
  if (!transport_ok) protocol.abortAudioStream();
  audio.cancelCapture();
  protocol.setAudioState(audio.stateMachine().state());
  audio_start_pending = false;
  audio_stop_requested = false;
  audio_stream_active = false;
  audio_speech_ended = false;
  audio_chunks_sent = 0;
  audio_started_at = 0;
#if PIPA_ALWAYS_LISTENING_ENABLED
  voice_activity.resetUtterance();
  clearPreRoll();
  if (deferred_upload_pending) clearDeferredAudio();
#endif
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
    audio_speech_ended = false;
    audio_started_at = millis();
#if PIPA_ALWAYS_LISTENING_ENABLED
    if (!deferred_upload_pending && !sendPreRoll()) {
      stopAudioCapture(false);
      return;
    }
#endif
  }

  if (!audio_stream_active) return;
#if PIPA_ALWAYS_LISTENING_ENABLED
  if (deferred_upload_pending) {
    const size_t remaining = deferred_audio_length - deferred_upload_offset;
    if (remaining == 0 || audio_chunks_sent >= kMaxAudioChunks) {
      audio.stateMachine().fail();
      stopAudioCapture(false);
      return;
    }
    const size_t captured = min(remaining, kAudioChunkBytes);
    const bool final = captured == remaining;
    const bool sent = protocol.sendAudioChunk(
        deferred_audio + deferred_upload_offset,
        captured,
        final);
    if (!sent) {
      audio.stateMachine().fail();
      stopAudioCapture(false);
      return;
    }
    memset(deferred_audio + deferred_upload_offset, 0, captured);
    deferred_upload_offset += captured;
    ++audio_chunks_sent;
    if (final) finishAudioCapture();
    return;
  }
#endif
  const size_t captured = audio.readMonoPcm(audio_chunk, sizeof(audio_chunk));
  if (captured == 0) {
    audio.stateMachine().fail();
    stopAudioCapture(false);
    return;
  }

  bool instruction_start_timed_out = false;
#if PIPA_ALWAYS_LISTENING_ENABLED
  const auto voice_event = voice_activity.process(
      reinterpret_cast<const int16_t*>(audio_chunk), captured / sizeof(int16_t)) ==
      pipa::PipaVoiceActivityEvent::kSpeechEnded;
  audio_speech_ended = audio_speech_ended || voice_event;
  instruction_start_timed_out = !audio_speech_ended && !voice_activity.speechActive() &&
      millis() - audio_started_at >= kInstructionStartTimeoutMs;
#endif
  const bool minimum_capture_elapsed = millis() - audio_started_at >= kMinimumCaptureMs;
  const bool final = audio_stop_requested ||
      (audio_speech_ended && minimum_capture_elapsed) || instruction_start_timed_out ||
      millis() - audio_started_at >= kMaxCaptureMs ||
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
#if PIPA_ALWAYS_LISTENING_ENABLED
    finishAudioCapture();
#else
    if (!audio.finishCapture()) audio.stateMachine().fail();
    protocol.setAudioState(audio.stateMachine().state());
    audio_start_pending = false;
    audio_stop_requested = false;
    audio_stream_active = false;
    audio_speech_ended = false;
    audio_chunks_sent = 0;
    audio_started_at = 0;
#endif
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
#if PIPA_ALWAYS_LISTENING_ENABLED
  deferred_audio = static_cast<uint8_t*>(heap_caps_calloc(
      1,
      kDeferredAudioBytes,
      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  log(deferred_audio != nullptr
          ? "offline voice buffer ready"
          : "offline voice buffer unavailable; Wake-on-LAN remains touch-only");
  const bool local_wake_ready = deferred_audio != nullptr && local_wake_phrase.begin();
  protocol.setLocalWakePhraseReady(local_wake_ready);
  log(local_wake_ready
          ? "local activation phrase ready"
          : "local activation phrase unavailable; hands-free audio disabled");
#endif
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
  protocol.maintainUi(millis());
  display.render(protocol.ui());
  maintainWifi();
  maintainPower();
  pollTouch();
#if PIPA_AUDIO_CAPTURE_ENABLED
#if PIPA_ALWAYS_LISTENING_ENABLED
  maintainHandsFreeMonitor();
#endif
  maintainAudioCapture();
#endif
  delay(10);
}
