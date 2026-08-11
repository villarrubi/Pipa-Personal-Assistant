#include "wake_on_lan.h"

namespace {

bool parseMac(const char* text, uint8_t mac[6]) {
  if (text == nullptr) return false;
  unsigned int values[6] = {};
  const bool parsed = sscanf(text, "%2x:%2x:%2x:%2x:%2x:%2x",
                             &values[0], &values[1], &values[2], &values[3],
                             &values[4], &values[5]) == 6 ||
                      sscanf(text, "%2x-%2x-%2x-%2x-%2x-%2x",
                             &values[0], &values[1], &values[2], &values[3],
                             &values[4], &values[5]) == 6;
  if (!parsed) {
    return false;
  }
  for (int value : values) {
    if (value < 0 || value > 255) return false;
  }
  for (size_t index = 0; index < 6; ++index) {
    mac[index] = static_cast<uint8_t>(values[index]);
  }
  return true;
}

}  // namespace

namespace pipa {

bool WakeOnLan::send(const char* mac_text) {
  uint8_t mac[6] = {};
  if (!parseMac(mac_text, mac)) return false;

  uint8_t packet[102] = {};
  for (size_t index = 0; index < 6; ++index) packet[index] = 0xFF;
  for (size_t repeat = 0; repeat < 16; ++repeat) {
    memcpy(packet + 6 + repeat * 6, mac, 6);
  }

  if (!udp_.beginPacket(IPAddress(255, 255, 255, 255), 9)) return false;
  udp_.write(packet, sizeof(packet));
  return udp_.endPacket() == 1;
}

}  // namespace pipa
