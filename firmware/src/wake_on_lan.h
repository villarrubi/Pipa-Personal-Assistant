#pragma once

#include <Arduino.h>
#include <WiFiUdp.h>

#include "wake_on_lan_packet.h"

namespace pipa {

class WakeOnLan {
 public:
  explicit WakeOnLan(WiFiUDP& udp) : udp_(udp) {}

  bool send(const char* mac_text);

 private:
  WiFiUDP& udp_;
};

}  // namespace pipa
