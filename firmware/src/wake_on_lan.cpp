#include "wake_on_lan.h"

namespace pipa {

bool WakeOnLan::send(const char* mac_text) {
  uint8_t packet[kWakeOnLanPacketSize] = {};
  if (!buildWakeOnLanPacket(mac_text, packet, sizeof(packet))) return false;

  if (!udp_.beginPacket(IPAddress(255, 255, 255, 255), 9)) return false;
  udp_.write(packet, sizeof(packet));
  return udp_.endPacket() == 1;
}

}  // namespace pipa
