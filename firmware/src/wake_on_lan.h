#pragma once

#include <Arduino.h>
#include <WiFiUdp.h>

namespace pipa {

class WakeOnLan {
 public:
  explicit WakeOnLan(WiFiUDP& udp) : udp_(udp) {}

  bool send(const char* mac_text);

 private:
  WiFiUDP& udp_;
};

}  // namespace pipa
