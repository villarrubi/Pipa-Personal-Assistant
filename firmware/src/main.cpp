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
#include "pipa_protocol.h"
#include "wake_on_lan.h"

namespace {

constexpr int kTouchSda = 1;
constexpr int kTouchScl = 3;
constexpr uint32_t kTouchDebounceMs = 800;
constexpr uint32_t kWolCooldownMs = 10000;
constexpr uint32_t kWifiRetryMs = 30000;

pipa::DeviceIdentity identity;
pipa::PipaProtocol protocol(Serial, identity, PIPA_DEVICE_ID, PIPA_FIRMWARE_VERSION);
WiFiUDP udp;
pipa::WakeOnLan wake_on_lan(udp);
pipa::Cst816Touch touch;
uint32_t last_touch = 0;
uint32_t last_wol = 0;
uint32_t last_wifi_attempt = 0;
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
      log(String("Wi-Fi ready: ") + WiFi.localIP().toString());
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
    protocol.sendGesture("tap");
  } else {
    maybeWakePc();
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(500);
  log(String("Pipa firmware ") + PIPA_FIRMWARE_VERSION + " starting");

  if (!identity.begin()) {
    log("FATAL: device identity could not be loaded or created");
    return;
  }
  log(String("PIPA_PUBLIC_KEY=") + identity.publicKeyBase64Url());

  protocol.begin();
  startWifiConnection();
  Wire.begin(kTouchSda, kTouchScl);
  log(touch.begin(Wire) ? "touch controller ready" : "touch controller unavailable");
  firmware_ready = true;
}

void loop() {
  if (!firmware_ready) {
    delay(1000);
    return;
  }
  protocol.poll();
  maintainWifi();
  pollTouch();
  delay(10);
}
